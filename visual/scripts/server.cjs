/**
 * server.cjs: HTTP + WebSocket server for the Designer visual companion.
 *
 * Uses only native Node.js modules (http, crypto, fs, path).
 * Serves HTML content from a session directory, injects helper.js,
 * wraps fragments in frame-template.html and notifies the browser
 * over WebSocket when the content changes.
 *
 * Configuration through environment variables:
 *   ALFRED_VISUAL_PORT     - Port (default 0 = free port chosen by the OS)
 *   ALFRED_VISUAL_HOST     - Listen address (default 127.0.0.1)
 *   ALFRED_VISUAL_URL_HOST - Host for URLs (default localhost)
 *   ALFRED_VISUAL_DIR      - Session directory (default /tmp/alfred-visual)
 *   ALFRED_VISUAL_OWNER_PID - PID of the parent process (optional)
 */

'use strict';

const http = require('node:http');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

// ---------------------------------------------------------------------------
// Constants and configuration
// ---------------------------------------------------------------------------

const HOST = process.env.ALFRED_VISUAL_HOST || '127.0.0.1';
const URL_HOST = process.env.ALFRED_VISUAL_URL_HOST || (HOST === '127.0.0.1' ? 'localhost' : HOST);
const SESSION_DIR = process.env.ALFRED_VISUAL_DIR || '/tmp/alfred-visual';
const OWNER_PID = process.env.ALFRED_VISUAL_OWNER_PID
  ? Number.parseInt(process.env.ALFRED_VISUAL_OWNER_PID, 10)
  : null;

/** Maximum idle time before the server shuts down (30 min). */
const IDLE_TIMEOUT_MS = 30 * 60 * 1000;

/** Interval to check that the parent process is still alive (60 s). */
const OWNER_CHECK_INTERVAL_MS = 60 * 1000;

/** Debounce for the file watcher (100 ms). */
const WATCH_DEBOUNCE_MS = 100;

/** Maximum accepted size for browser events (64 KiB). */
const MAX_EVENT_BODY_BYTES = 64 * 1024;

/** Maximum size of persisted event fields. */
const MAX_EVENT_FIELD_CHARS = 512;

const CONTENT_DIR = path.join(SESSION_DIR, 'content');
const STATE_DIR = path.join(SESSION_DIR, 'state');
const DEBUG_WS = process.env.ALFRED_VISUAL_DEBUG_WS === '1';

function debugWs(message, details) {
  if (!DEBUG_WS) return;
  const payload = details === undefined ? '' : ` ${JSON.stringify(details)}`;
  process.stderr.write(`[visual-ws] ${message}${payload}\n`);
}

// ---------------------------------------------------------------------------
// WebSocket RFC 6455: minimal implementation
// ---------------------------------------------------------------------------

/** Opcodes defined in RFC 6455, section 5.2. */
const OPCODES = {
  TEXT: 0x01,
  CLOSE: 0x08,
  PING: 0x09,
  PONG: 0x0a,
};

/**
 * Computes the accept key for the WebSocket handshake.
 * @param {string} key - Value of the Sec-WebSocket-Key header.
 * @returns {string} Base64 SHA-1 hash per RFC 6455, section 4.2.2.
 */
function computeAcceptKey(key) {
  const MAGIC = '258EAFA5-E914-47DA-95CA-5AB5DC76B51E';
  return crypto
    .createHash('sha1')
    .update(key + MAGIC)
    .digest('base64');
}

/**
 * Normalizes headers that should hold a single value.
 * Some clients or proxies send them as an array or as a
 * comma-separated list. For the WebSocket handshake we use
 * only the first meaningful token.
 * @param {string|string[]|undefined} value
 * @returns {string}
 */
function normalizeSingleHeader(value) {
  if (Array.isArray(value)) {
    return String(value[0] || '').trim();
  }
  return String(value || '').split(',')[0].trim();
}

/**
 * Checks if an HTTP header contains a given comma-separated token.
 * @param {string|string[]|undefined} value
 * @param {string} token
 * @returns {boolean}
 */
function headerHasToken(value, token) {
  const rawValues = Array.isArray(value) ? value : [value];
  return rawValues.some((raw) => String(raw || '')
    .split(',')
    .map((part) => part.trim().toLowerCase())
    .includes(token.toLowerCase()));
}

/**
 * Checks that Sec-WebSocket-Key is 16 bytes of base64, as RFC 6455 requires.
 * @param {string} key
 * @returns {boolean}
 */
function isValidWebSocketKey(key) {
  if (!key) return false;
  try {
    const decoded = Buffer.from(key, 'base64');
    return decoded.length === 16 && decoded.toString('base64') === key;
  } catch {
    return false;
  }
}

/**
 * Encodes a WebSocket frame to send to the client.
 * @param {number} opcode - Opcode (TEXT, CLOSE, PING, PONG).
 * @param {Buffer|string} payload - Data to send.
 * @returns {Buffer} WebSocket frame ready to write to the socket.
 */
function encodeFrame(opcode, payload) {
  const data = Buffer.isBuffer(payload) ? payload : Buffer.from(payload, 'utf8');
  const len = data.length;
  let header;

  if (len < 126) {
    header = Buffer.alloc(2);
    header[0] = 0x80 | opcode;
    header[1] = len;
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x80 | opcode;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x80 | opcode;
    header[1] = 127;
    // Use writeBigUInt64BE for large lengths
    header.writeBigUInt64BE(BigInt(len), 2);
  }

  return Buffer.concat([header, data]);
}

/**
 * Decodes a WebSocket frame received from the client.
 * Clients always send masked data (RFC section 5.3).
 * @param {Buffer} buf - Raw socket data.
 * @returns {{ opcode: number, payload: Buffer, totalLength: number } | null}
 *   null if the buffer is incomplete.
 */
function decodeFrame(buf) {
  if (buf.length < 2) return null;

  const opcode = buf[0] & 0x0f;
  const masked = (buf[1] & 0x80) !== 0;
  let payloadLen = buf[1] & 0x7f;
  let offset = 2;

  if (payloadLen === 126) {
    if (buf.length < 4) return null;
    payloadLen = buf.readUInt16BE(2);
    offset = 4;
  } else if (payloadLen === 127) {
    if (buf.length < 10) return null;
    payloadLen = Number(buf.readBigUInt64BE(2));
    offset = 10;
  }

  const maskSize = masked ? 4 : 0;
  const totalLength = offset + maskSize + payloadLen;
  if (buf.length < totalLength) return null;

  let payload;
  if (masked) {
    const mask = buf.slice(offset, offset + maskSize);
    payload = Buffer.alloc(payloadLen);
    for (let i = 0; i < payloadLen; i++) {
      payload[i] = buf[offset + maskSize + i] ^ mask[i % 4];
    }
  } else {
    payload = buf.slice(offset, offset + payloadLen);
  }

  return { opcode, payload, totalLength };
}

// ---------------------------------------------------------------------------
// File utilities
// ---------------------------------------------------------------------------

/**
 * Gets the newest .html file in the content directory.
 * @returns {string|null} Absolute path, or null if there are no HTML files.
 */
function getNewestHtml() {
  let files;
  try {
    files = fs.readdirSync(CONTENT_DIR);
  } catch {
    return null;
  }

  const htmlFiles = files
    .filter((f) => f.endsWith('.html'))
    .map((f) => {
      const full = path.join(CONTENT_DIR, f);
      try {
        return { name: f, mtime: fs.statSync(full).mtimeMs, path: full };
      } catch {
        return null;
      }
    })
    .filter(Boolean)
    .sort((a, b) => b.mtime - a.mtime);

  return htmlFiles.length > 0 ? htmlFiles[0].path : null;
}

/**
 * Tells if HTML content is a full document or a fragment.
 * A full document starts with <!DOCTYPE (whitespace ignored).
 * @param {string} html - HTML content.
 * @returns {boolean}
 */
function isFullDocument(html) {
  return /^\s*<!DOCTYPE/i.test(html);
}

/** Loads helper.js from the directory of this file. */
function loadHelperJs() {
  return fs.readFileSync(path.join(__dirname, 'helper.js'), 'utf8');
}

/** Loads frame-template.html from the directory of this file. */
function loadFrameTemplate() {
  return fs.readFileSync(path.join(__dirname, 'frame-template.html'), 'utf8');
}

/**
 * Injects helper.js as an inline script just before </body>.
 * If there is no </body>, appends it at the end.
 * @param {string} html - Full HTML document.
 * @returns {string}
 */
function injectHelper(html) {
  const script = `<script>\n${loadHelperJs()}\n</script>`;
  if (html.includes('</body>')) {
    return html.replace('</body>', script + '\n</body>');
  }
  return html + '\n' + script;
}

/**
 * Extracts style blocks that should move to the frame <head>.
 * Currently used for font imports generated by Designer.
 * @param {string} fragment
 * @returns {{ fragment: string, headHtml: string }}
 */
function extractHeadMarkup(fragment) {
  const matches = [];
  const cleaned = fragment.replace(/<style class="style-font-imports">[\s\S]*?<\/style>/g, (match) => {
    matches.push(match);
    return '';
  });
  return {
    fragment: cleaned.trim(),
    headHtml: matches.join('\n'),
  };
}

/**
 * Wraps an HTML fragment in frame-template and injects helper.js.
 * @param {string} fragment - HTML fragment without DOCTYPE.
 * @returns {string}
 */
function wrapInFrame(fragment) {
  const template = loadFrameTemplate();
  const { fragment: bodyFragment, headHtml } = extractHeadMarkup(fragment);
  let wrapped = template.replace('<!-- CONTENT -->', bodyFragment);
  if (headHtml && wrapped.includes('</head>')) {
    wrapped = wrapped.replace('</head>', `${headHtml}\n</head>`);
  }
  return injectHelper(wrapped);
}

/** Waiting page shown while there is no HTML content yet. */
function waitingPage() {
  const template = loadFrameTemplate();
  const msg = '<p class="waiting-message">Ждём, пока Designer подготовит варианты стиля...</p>';
  const wrapped = template.replace('<!-- CONTENT -->', msg);
  return injectHelper(wrapped);
}

// ---------------------------------------------------------------------------
// Basic MIME types for static files
// ---------------------------------------------------------------------------

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

/** Security headers applied to all HTTP responses. */
const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Cache-Control': 'no-store',
};

// ---------------------------------------------------------------------------
// Global server state
// ---------------------------------------------------------------------------

/** Active WebSocket connections. */
const wsClients = new Set();

/** Timestamp of the last activity (for the idle timeout). */
let lastActivity = Date.now();

/** Known files in the content directory. */
let knownFiles = new Set();

/** Global reference to the HTTP server (needed for the WS origin check). */
let _httpServer = null;

// ---------------------------------------------------------------------------
// JSON messages on stdout
// ---------------------------------------------------------------------------

/**
 * Writes a JSON message to stdout.
 * Each message takes exactly one line.
 * @param {object} msg - Object to serialize.
 */
function emit(msg) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}

/**
 * Clears the event log of the current visual screen.
 * Used when the screen changes, so that clicks from an older
 * version of the HTML are not reused.
 */
function clearEventLog() {
  try {
    fs.writeFileSync(path.join(STATE_DIR, 'events'), '');
  } catch {
    // A failure here is harmless
  }
}

/**
 * Normalizes a user click to the canonical format of the visual contract.
 * Keeps legacy fields for compatibility with existing integrations.
 * @param {object} event
 * @returns {object}
 */
function buildChoiceEvent(event) {
  const ts = new Date().toISOString();
  return {
    source: 'user-event',
    type: 'click',
    choice: event.choice,
    label: event.label,
    element: event.element || '.style-option',
    ts,
    timestamp: ts,
  };
}

/**
 * Normalizes input from the browser before it is persisted.
 * @param {unknown} event
 * @returns {{choice: string, label: string, element: string}|null}
 */
function normalizeChoiceEventInput(event) {
  if (!event || typeof event !== 'object' || Array.isArray(event)) {
    return null;
  }

  const choice = event.choice;
  if (typeof choice !== 'string' || choice.trim() === '' || choice.length > MAX_EVENT_FIELD_CHARS) {
    return null;
  }

  const label = typeof event.label === 'string' && event.label.length <= MAX_EVENT_FIELD_CHARS
    ? event.label
    : choice;
  const element = typeof event.element === 'string' && event.element.length <= MAX_EVENT_FIELD_CHARS
    ? event.element
    : '.style-option';

  return { choice, label, element };
}

/**
 * Records a canonical choice in the event log and writes it to stdout.
 * @param {object} event
 * @returns {object}
 */
function recordChoiceEvent(event) {
  const normalizedEvent = normalizeChoiceEventInput(event);
  if (!normalizedEvent) return null;
  const choiceEvent = buildChoiceEvent(normalizedEvent);
  const eventLine = JSON.stringify(choiceEvent);
  fs.appendFileSync(path.join(STATE_DIR, 'events'), eventLine + '\n');
  emit(choiceEvent);
  return choiceEvent;
}

/**
 * Returns the set of allowed origins for local WebSocket connections.
 * Accepts loopback aliases so that localhost and 127.0.0.1 stay equivalent.
 * @returns {Set<string>}
 */
function getAllowedOrigins() {
  const port = _httpServer && _httpServer.address() && typeof _httpServer.address() === 'object'
    ? _httpServer.address().port
    : '';
  const hosts = new Set([URL_HOST, HOST]);

  if (hosts.has('127.0.0.1') || hosts.has('localhost')) {
    hosts.add('127.0.0.1');
    hosts.add('localhost');
  }

  if (hosts.has('::1')) {
    hosts.add('[::1]');
  }

  const origins = new Set();
  for (const host of hosts) {
    if (!host) continue;
    origins.add(`http://${host}:${port}`);
  }
  return origins;
}

// ---------------------------------------------------------------------------
// HTTP handler
// ---------------------------------------------------------------------------

/**
 * Serves a static file from the content directory.
 * Protects against path traversal by resolving the real path with realpathSync.
 * @param {http.IncomingMessage} req
 * @param {http.ServerResponse} res
 */
function serveStaticFile(req, res) {
  let relPath;
  try {
    relPath = decodeURIComponent(req.url.slice('/files/'.length));
  } catch {
    res.writeHead(400, SECURITY_HEADERS);
    res.end('Invalid path');
    return;
  }
  const filePath = path.join(CONTENT_DIR, relPath);

  // Path traversal protection: resolve the real path to detect symlinks
  const resolvedBase = fs.realpathSync(CONTENT_DIR);
  let resolvedPath;
  try {
    resolvedPath = fs.realpathSync(filePath);
  } catch {
    res.writeHead(404, SECURITY_HEADERS);
    res.end('Not found');
    return;
  }

  if (!resolvedPath.startsWith(resolvedBase + path.sep) && resolvedPath !== resolvedBase) {
    res.writeHead(403, SECURITY_HEADERS);
    res.end('Forbidden');
    return;
  }

  try {
    const data = fs.readFileSync(resolvedPath);
    const ext = path.extname(resolvedPath).toLowerCase();
    const mime = MIME_TYPES[ext] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': mime, ...SECURITY_HEADERS });
    res.end(data);
  } catch {
    res.writeHead(404, SECURITY_HEADERS);
    res.end('Not found');
  }
}

/**
 * Handles incoming HTTP requests.
 * - GET / serves the newest HTML (or the waiting page).
 * - GET /files/* serves static files from the content directory.
 */
function handleRequest(req, res) {
  lastActivity = Date.now();

  if (req.method === 'POST' && req.url === '/events') {
    const contentLength = Number.parseInt(normalizeSingleHeader(req.headers['content-length']) || '0', 10);
    if (Number.isFinite(contentLength) && contentLength > MAX_EVENT_BODY_BYTES) {
      res.writeHead(413, SECURITY_HEADERS);
      res.end('Event too large');
      return;
    }

    const chunks = [];
    let receivedBytes = 0;
    let tooLarge = false;
    req.on('data', (chunk) => {
      receivedBytes += chunk.length;
      if (receivedBytes > MAX_EVENT_BODY_BYTES) {
        tooLarge = true;
        chunks.length = 0;
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (tooLarge) {
        res.writeHead(413, SECURITY_HEADERS);
        res.end('Event too large');
        return;
      }

      try {
        const body = Buffer.concat(chunks).toString('utf8');
        const event = JSON.parse(body || '{}');
        if (!normalizeChoiceEventInput(event)) {
          res.writeHead(400, SECURITY_HEADERS);
          res.end('Invalid event');
          return;
        }
        recordChoiceEvent(event);
        res.writeHead(202, SECURITY_HEADERS);
        res.end('accepted');
      } catch {
        res.writeHead(400, SECURITY_HEADERS);
        res.end('Invalid JSON');
      }
    });
    return;
  }

  if (req.url === '/' || req.url === '/index.html') {
    const newest = getNewestHtml();
    let body;

    if (!newest) {
      body = waitingPage();
    } else {
      try {
        const raw = fs.readFileSync(newest, 'utf8');
        // helper.js uses textContent (not innerHTML) to prevent XSS
        body = isFullDocument(raw) ? injectHelper(raw) : wrapInFrame(raw);
      } catch {
        body = waitingPage();
      }
    }

    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', ...SECURITY_HEADERS });
    res.end(body);
    return;
  }

  if (req.url.startsWith('/files/')) {
    serveStaticFile(req, res);
    return;
  }

  res.writeHead(404, SECURITY_HEADERS);
  res.end('Not found');
}

// ---------------------------------------------------------------------------
// WebSocket handling
// ---------------------------------------------------------------------------

/**
 * Broadcasts a message to all active WebSocket connections.
 * @param {string} message - Serialized JSON message.
 */
function broadcast(message) {
  const frame = encodeFrame(OPCODES.TEXT, message);
  for (const socket of wsClients) {
    try {
      socket.write(frame);
    } catch {
      wsClients.delete(socket);
    }
  }
}

/**
 * Handles the HTTP upgrade to WebSocket per RFC 6455.
 * @param {http.IncomingMessage} req
 * @param {net.Socket} socket
 */
function handleUpgrade(req, socket, head) {
  const rejectUpgrade = (reason) => {
    debugWs('upgrade-rejected', { reason });
    try {
      socket.write('HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n');
    } catch {
      // The connection can already be closed.
    }
    socket.destroy();
  };

  if (!headerHasToken(req.headers.upgrade, 'websocket')) {
    rejectUpgrade('missing-upgrade-websocket');
    return;
  }
  if (!headerHasToken(req.headers.connection, 'upgrade')) {
    rejectUpgrade('missing-connection-upgrade');
    return;
  }
  if (normalizeSingleHeader(req.headers['sec-websocket-version']) !== '13') {
    rejectUpgrade('unsupported-websocket-version');
    return;
  }

  // Check the WebSocket origin to block connections from foreign domains
  const origin = normalizeSingleHeader(req.headers['origin']);
  debugWs('upgrade-request', {
    origin,
    key: normalizeSingleHeader(req.headers['sec-websocket-key']),
    headers: req.headers,
    headLength: head ? head.length : 0,
  });
  if (origin) {
    const allowedOrigins = getAllowedOrigins();
    if (!allowedOrigins.has(origin)) {
      debugWs('upgrade-rejected-origin', { origin, allowedOrigins: Array.from(allowedOrigins) });
      rejectUpgrade('origin-not-allowed');
      return;
    }
  }

  const key = normalizeSingleHeader(req.headers['sec-websocket-key']);
  if (!isValidWebSocketKey(key)) {
    debugWs('upgrade-rejected-missing-key');
    rejectUpgrade('invalid-websocket-key');
    return;
  }

  const accept = computeAcceptKey(key);
  debugWs('upgrade-accepted', { accept });
  const headers = [
    'HTTP/1.1 101 Switching Protocols',
    'Upgrade: websocket',
    'Connection: Upgrade',
    `Sec-WebSocket-Accept: ${accept}`,
    '',
    '',
  ].join('\r\n');

  socket.write(headers);
  wsClients.add(socket);
  lastActivity = Date.now();

  let buffer = Buffer.alloc(0);
  socket.setNoDelay(true);

  function processChunk(chunk) {
    if (!chunk || chunk.length === 0) return;
    buffer = Buffer.concat([buffer, chunk]);

    // Process all complete frames in the buffer
    let frame;
    while ((frame = decodeFrame(buffer)) !== null) {
      buffer = buffer.slice(frame.totalLength);

      switch (frame.opcode) {
        case OPCODES.TEXT: {
          const text = frame.payload.toString('utf8');
          try {
            const event = JSON.parse(text);
            // If the event contains a choice, record it
            if (normalizeChoiceEventInput(event)) {
              recordChoiceEvent(event);
            }
          } catch {
            // Not a JSON message, ignore it
          }
          break;
        }
        case OPCODES.PING:
          socket.write(encodeFrame(OPCODES.PONG, frame.payload));
          break;
        case OPCODES.CLOSE:
          socket.write(encodeFrame(OPCODES.CLOSE, Buffer.alloc(0)));
          wsClients.delete(socket);
          socket.end();
          break;
      }
    }
  }

  if (head && head.length > 0) {
    processChunk(head);
  }

  socket.on('data', (chunk) => {
    lastActivity = Date.now();
    processChunk(chunk);
  });

  socket.on('close', () => wsClients.delete(socket));
  socket.on('error', () => wsClients.delete(socket));
}

// ---------------------------------------------------------------------------
// File watching (fs.watch with debounce)
// ---------------------------------------------------------------------------

/**
 * Starts watching the content directory.
 * On a new file, clears the events and broadcasts a reload.
 * On an update to an existing file, clears the events and broadcasts a reload.
 */
function startWatcher() {
  // Load the initial known files
  try {
    const files = fs.readdirSync(CONTENT_DIR);
    knownFiles = new Set(files.filter((f) => f.endsWith('.html')));
  } catch {
    // The directory may not exist yet
  }

  let debounceTimer = null;

  try {
    fs.watch(CONTENT_DIR, (eventType, filename) => {
      if (!filename || !filename.endsWith('.html')) return;

      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        const isNew = !knownFiles.has(filename);

        if (isNew) {
          // New file: clear the events and notify
          knownFiles.add(filename);
          clearEventLog();
          emit({ type: 'screen-added', file: filename });
        } else {
          clearEventLog();
          emit({ type: 'screen-updated', file: filename });
        }

        broadcast(JSON.stringify({ type: 'reload' }));
      }, WATCH_DEBOUNCE_MS);
    });
  } catch {
    // If the directory does not exist, the watcher does not start. This is not critical
  }
}

// ---------------------------------------------------------------------------
// Lifecycle management
// ---------------------------------------------------------------------------

/**
 * Writes the server info to the state directory.
 * @param {object} info - Server data (port, host, URL, and so on).
 */
function writeServerInfo(info) {
  try {
    fs.writeFileSync(path.join(STATE_DIR, 'server-info'), JSON.stringify(info, null, 2));
  } catch {
    // A failure here is not critical
  }
}

/**
 * Stops the server cleanly, notifies on stdout and writes
 * the server-stopped file.
 * @param {string} reason - Reason for the shutdown.
 */
function shutdown(reason) {
  emit({ type: 'server-stopped', reason });
  try {
    fs.writeFileSync(path.join(STATE_DIR, 'server-stopped'), JSON.stringify({ reason, timestamp: new Date().toISOString() }));
  } catch {
    // Ignore errors during shutdown
  }

  // Close all WebSocket connections
  for (const socket of wsClients) {
    try {
      socket.write(encodeFrame(OPCODES.CLOSE, Buffer.alloc(0)));
      socket.end();
    } catch {
      // Ignore
    }
  }

  process.exit(0);
}

/**
 * Checks if the parent process is still alive.
 * If OWNER_PID is set and the process no longer exists, shuts down the server.
 */
function checkOwnerAlive() {
  if (OWNER_PID === null) return;
  try {
    process.kill(OWNER_PID, 0);
  } catch {
    shutdown('owner-exited');
  }
}

// ---------------------------------------------------------------------------
// Server startup
// ---------------------------------------------------------------------------

/**
 * Main entry point.
 * Creates the required directories, starts the HTTP server and sets up
 * the idle timer and the parent process watch.
 */
function main() {
  // Make sure the session directories exist
  fs.mkdirSync(CONTENT_DIR, { recursive: true });
  fs.mkdirSync(STATE_DIR, { recursive: true });

  // Pick the port: a valid environment variable or a free port assigned by the OS.
  const rawPort = process.env.ALFRED_VISUAL_PORT;
  const requestedPort = rawPort === undefined || rawPort === ''
    ? 0
    : Number.parseInt(rawPort, 10);
  if (!Number.isInteger(requestedPort) || requestedPort < 0 || requestedPort > 65535) {
    process.stderr.write(`Invalid port for ALFRED_VISUAL_PORT: ${rawPort}\n`);
    process.exit(1);
  }

  const server = http.createServer(handleRequest);
  _httpServer = server;
  server.on('upgrade', handleUpgrade);
  server.on('error', (error) => {
    process.stderr.write(`Failed to start the visual server: ${error.message}\n`);
    process.exit(1);
  });

  server.listen(requestedPort, HOST, () => {
    const address = server.address();
    const actualPort = address && typeof address === 'object' ? address.port : requestedPort;
    const url = `http://${URL_HOST}:${actualPort}`;
    const info = {
      type: 'server-started',
      port: actualPort,
      host: HOST,
      url_host: URL_HOST,
      url,
      session_dir: SESSION_DIR,
      server_pid: process.pid,
      screen_dir: CONTENT_DIR,
      state_dir: STATE_DIR,
    };

    writeServerInfo(info);
    emit(info);

    // Start file watching
    startWatcher();

    // Idle timer (30 min)
    setInterval(() => {
      if (Date.now() - lastActivity > IDLE_TIMEOUT_MS) {
        shutdown('idle-timeout');
      }
    }, 60 * 1000);

    // Periodic check of the parent process
    if (OWNER_PID !== null) {
      setInterval(checkOwnerAlive, OWNER_CHECK_INTERVAL_MS);
    }
  });

  // Clean shutdown on system signals
  process.on('SIGTERM', () => shutdown('sigterm'));
  process.on('SIGINT', () => shutdown('sigint'));
}

// Run only as the main module (not when imported by tests)
if (require.main === module) {
  main();
}

// ---------------------------------------------------------------------------
// Exports for tests
// ---------------------------------------------------------------------------

module.exports = { computeAcceptKey, encodeFrame, decodeFrame, OPCODES };
