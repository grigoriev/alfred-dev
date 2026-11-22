"""
test_visual_server.py: integration tests for the Designer visual server.

Check the server lifecycle (startup, HTTP response, state writes). The
tests use subprocess to launch server.cjs and http.client for requests.
Each test creates a temporary session directory with the content/ and
state/ subfolders.
"""

import http.client
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from base64 import b64encode

# Path to the server, relative to the project root
SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'visual', 'scripts', 'server.cjs',
)


class TestServerLifecycle(unittest.TestCase):
    """
    Integration tests for server.cjs.

    Each test starts a server instance on a random port, runs the checks
    and cleans up the resources at the end.
    """

    def setUp(self):
        """Create the temporary session directory with content/ and state/."""
        self.session_dir = tempfile.mkdtemp(prefix='alfred-visual-test-')
        self.content_dir = os.path.join(self.session_dir, 'content')
        self.state_dir = os.path.join(self.session_dir, 'state')
        os.makedirs(self.content_dir)
        os.makedirs(self.state_dir)
        self.proc = None
        self.port = None

    def tearDown(self):
        """Stop the server and remove the temporary directory."""
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        shutil.rmtree(self.session_dir, ignore_errors=True)

    def _start_server(self, extra_env=None):
        """
        Start the server and wait for the startup message on stdout.

        Return the JSON dict of the server-started message.
        Raise AssertionError if the server does not start in 10 seconds.
        """
        env = os.environ.copy()
        env['ALFRED_VISUAL_DIR'] = self.session_dir
        env['ALFRED_VISUAL_HOST'] = '127.0.0.1'
        if extra_env:
            env.update(extra_env)

        self.proc = subprocess.Popen(
            ['node', SERVER_PATH],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        # Read the first stdout line (startup message)
        # with a 10-second timeout
        import select
        start = time.time()
        line = b''
        while time.time() - start < 10:
            # Read what is available
            ready, _, _ = select.select([self.proc.stdout], [], [], 1.0)
            if ready:
                chunk = self.proc.stdout.read1(4096) if hasattr(self.proc.stdout, 'read1') else self.proc.stdout.readline()
                line += chunk
                if b'\n' in line:
                    break

        self.assertIn(b'\n', line, 'The server did not emit a startup message in 10s')

        first_line = line.split(b'\n')[0]
        info = json.loads(first_line)
        self.assertEqual(info['type'], 'server-started')
        self.port = info['port']
        return info

    def _get(self, path='/'):
        """Send a GET request to the server and return (status, body)."""
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('GET', path)
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        status = resp.status
        conn.close()
        return status, body

    def _post_json(self, path, payload):
        """Send a JSON POST request and return (status, body)."""
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        body = json.dumps(payload)
        conn.request('POST', path, body=body, headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        status = resp.status
        conn.close()
        return status, data

    def _open_websocket(self):
        """Open a minimal WebSocket connection to the visual server."""
        return self._open_websocket_with_origin(None)

    def _open_websocket_with_origin(self, origin):
        """Open a minimal WebSocket connection to the visual server."""
        sock = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        key = b64encode(os.urandom(16)).decode('ascii')
        lines = [
            'GET / HTTP/1.1',
            f'Host: 127.0.0.1:{self.port}',
            'Upgrade: websocket',
            'Connection: Upgrade',
            f'Sec-WebSocket-Key: {key}',
            'Sec-WebSocket-Version: 13',
        ]
        if origin is not None:
            lines.append(f'Origin: {origin}')
        lines.extend(['', ''])
        request = '\r\n'.join(lines).encode('ascii')
        sock.sendall(request)

        response = b''
        while b'\r\n\r\n' not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        self.assertIn(b'101 Switching Protocols', response)
        return sock

    def _websocket_handshake_response(self, lines):
        """Send a manual WebSocket handshake and return the raw response."""
        sock = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        try:
            sock.sendall('\r\n'.join(lines).encode('ascii'))
            response = b''
            while b'\r\n\r\n' not in response:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
            return response
        finally:
            sock.close()

    def _recv_ws_text(self, sock):
        """Receive an unmasked text frame sent by the server."""
        first = sock.recv(2)
        self.assertEqual(len(first), 2)
        length = first[1] & 0x7F

        if length == 126:
            length = struct.unpack('!H', sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack('!Q', sock.recv(8))[0]

        payload = b''
        while len(payload) < length:
            payload += sock.recv(length - len(payload))

        return payload.decode('utf-8')

    def _send_ws_text(self, sock, text):
        """Send a masked WebSocket text frame, as a browser would."""
        payload = text.encode('utf-8')
        header = bytearray([0x81])
        length = len(payload)

        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack('!H', length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack('!Q', length))

        mask = os.urandom(4)
        masked = bytes(payload[i] ^ mask[i % 4] for i in range(length))
        sock.sendall(bytes(header) + mask + masked)

    # -- Tests ---------------------------------------------------------------

    def test_server_starts_and_returns_info(self):
        """The server starts and emits valid JSON with type server-started."""
        info = self._start_server()
        self.assertEqual(info['type'], 'server-started')
        self.assertIn('port', info)
        self.assertIn('url', info)
        self.assertEqual(info['session_dir'], self.session_dir)
        self.assertEqual(info['server_pid'], self.proc.pid)
        self.assertIn('screen_dir', info)
        self.assertIn('state_dir', info)

    def test_server_accepts_port_zero_and_reports_real_port(self):
        """ALFRED_VISUAL_PORT=0 lets the OS choose a free usable port."""
        info = self._start_server({'ALFRED_VISUAL_PORT': '0'})
        self.assertGreater(info['port'], 0)
        self.assertIn(f":{info['port']}", info['url'])

    def test_server_serves_waiting_page(self):
        """Without HTML content, GET / returns the waiting page."""
        self._start_server()
        status, body = self._get('/')
        self.assertEqual(status, 200)
        self.assertIn('Ждём', body)

    def test_server_serves_newest_html(self):
        """After an HTML file is written, GET / includes it in the response."""
        self._start_server()

        # Write a content file
        html_content = '<div class="style-grid"><p>Hello world</p></div>'
        html_path = os.path.join(self.content_dir, 'style-001.html')
        with open(html_path, 'w') as f:
            f.write(html_content)

        # Give the file system time
        time.sleep(0.5)

        status, body = self._get('/')
        self.assertEqual(status, 200)
        self.assertIn('Hello world', body)

    def test_server_wraps_fragments_in_frame(self):
        """A fragment without DOCTYPE is wrapped in the frame (contains 'Designer')."""
        self._start_server()

        fragment = '<p>Test fragment</p>'
        with open(os.path.join(self.content_dir, 'frag.html'), 'w') as f:
            f.write(fragment)

        time.sleep(0.5)

        status, body = self._get('/')
        self.assertEqual(status, 200)
        self.assertIn('Designer', body)
        self.assertIn('Test fragment', body)

    def test_server_moves_font_imports_from_fragment_to_head(self):
        """Designer font imports must end up in the frame <head>."""
        self._start_server()

        fragment = (
            '<style class="style-font-imports">@import url("https://fonts.googleapis.com/css2?family=Archivo+Black&display=swap");</style>'
            '<div class="style-grid"><p>Preview with typography</p></div>'
        )
        with open(os.path.join(self.content_dir, 'fonts.html'), 'w', encoding='utf-8') as f:
            f.write(fragment)

        time.sleep(0.5)

        status, body = self._get('/')
        self.assertEqual(status, 200)
        self.assertIn('@import url("https://fonts.googleapis.com/css2?family=Archivo+Black&display=swap");', body)
        self.assertLess(body.index('style-font-imports'), body.index('</head>'))
        self.assertGreater(body.index('Preview with typography'), body.index('<body>'))

    def test_server_serves_full_documents_as_is(self):
        """A full document with DOCTYPE is served without the frame wrapper."""
        self._start_server()

        full_doc = '<!DOCTYPE html><html><head><title>Test</title></head><body><p>Full document</p></body></html>'
        with open(os.path.join(self.content_dir, 'full.html'), 'w') as f:
            f.write(full_doc)

        time.sleep(0.5)

        status, body = self._get('/')
        self.assertEqual(status, 200)
        self.assertIn('Full document', body)
        # A full document must NOT contain the Designer frame header
        # (unless the document itself includes it).
        # Verify that it does not have the frame alfred-header class.
        self.assertNotIn('alfred-header', body)

    def test_server_rejects_malformed_static_path_without_crashing(self):
        """A malformed URL under /files must not crash the server."""
        self._start_server()
        status, body = self._get('/files/%E0%A4%A')
        self.assertEqual(status, 400)
        self.assertIn('Invalid path', body)

        status_after, _ = self._get('/')
        self.assertEqual(status_after, 200)

    def test_server_writes_server_info(self):
        """The state/server-info file exists after startup."""
        self._start_server()

        info_path = os.path.join(self.state_dir, 'server-info')
        self.assertTrue(
            os.path.exists(info_path),
            f'Not found: {info_path}',
        )

        with open(info_path) as f:
            info = json.loads(f.read())
        self.assertEqual(info['type'], 'server-started')
        self.assertEqual(info['port'], self.port)

    def test_server_records_click_events_with_canonical_shape(self):
        """WS clicks are stored with the canonical contract that Designer expects."""
        self._start_server()
        ws = self._open_websocket()
        try:
            self._send_ws_text(ws, json.dumps({'choice': 'A', 'label': 'Warm editorial'}))
            time.sleep(0.2)
        finally:
            ws.close()

        events_path = os.path.join(self.state_dir, 'events')
        with open(events_path, 'r', encoding='utf-8') as fh:
            lines = [line.strip() for line in fh if line.strip()]

        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(event['type'], 'click')
        self.assertEqual(event['choice'], 'A')
        self.assertEqual(event['label'], 'Warm editorial')
        self.assertEqual(event['element'], '.style-option')
        self.assertEqual(event['source'], 'user-event')
        self.assertIn('ts', event)
        self.assertIn('timestamp', event)

    def test_server_records_http_click_events_for_browser_fallback(self):
        """The HTTP fallback must record the human choice when WS does not connect."""
        self._start_server()
        status, _ = self._post_json('/events', {'choice': 'C', 'label': 'Modern SaaS clean'})
        self.assertEqual(status, 202)

        events_path = os.path.join(self.state_dir, 'events')
        with open(events_path, 'r', encoding='utf-8') as fh:
            lines = [line.strip() for line in fh if line.strip()]

        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(event['choice'], 'C')
        self.assertEqual(event['label'], 'Modern SaaS clean')
        self.assertEqual(event['type'], 'click')

    def test_server_rejects_invalid_http_click_event_shape(self):
        """The HTTP fallback must not persist events without a valid choice."""
        self._start_server()
        status, body = self._post_json('/events', {'choice': 42, 'label': 'Not valid'})
        self.assertEqual(status, 400)
        self.assertIn('Invalid event', body)
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, 'events')))

    def test_server_rejects_oversized_http_click_event(self):
        """The events endpoint must not accept arbitrarily large bodies."""
        self._start_server()
        status, body = self._post_json('/events', {'choice': 'A' * (70 * 1024), 'label': 'Large'})
        self.assertEqual(status, 413)
        self.assertIn('Event too large', body)
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, 'events')))

    def test_server_accepts_loopback_origin_alias_for_websocket(self):
        """Opening the URL as 127.0.0.1 must not break WS if the server announced localhost."""
        self._start_server()
        ws = self._open_websocket_with_origin(f'http://127.0.0.1:{self.port}')
        try:
            self._send_ws_text(ws, json.dumps({'choice': 'A', 'label': 'Alias loopback'}))
            time.sleep(0.2)
        finally:
            ws.close()

        events_path = os.path.join(self.state_dir, 'events')
        with open(events_path, 'r', encoding='utf-8') as fh:
            lines = [line.strip() for line in fh if line.strip()]
        self.assertEqual(len(lines), 1)

    def test_server_rejects_invalid_websocket_handshake(self):
        """The WS upgrade requires version 13 and an RFC 6455 Sec-WebSocket-Key."""
        self._start_server()
        invalid_key_response = self._websocket_handshake_response([
            'GET / HTTP/1.1',
            f'Host: 127.0.0.1:{self.port}',
            'Upgrade: websocket',
            'Connection: Upgrade',
            'Sec-WebSocket-Key: not-base64',
            'Sec-WebSocket-Version: 13',
            '',
            '',
        ])
        invalid_version_response = self._websocket_handshake_response([
            'GET / HTTP/1.1',
            f'Host: 127.0.0.1:{self.port}',
            'Upgrade: websocket',
            'Connection: Upgrade',
            f'Sec-WebSocket-Key: {b64encode(os.urandom(16)).decode("ascii")}',
            'Sec-WebSocket-Version: 12',
            '',
            '',
        ])

        self.assertIn(b'400 Bad Request', invalid_key_response)
        self.assertIn(b'400 Bad Request', invalid_version_response)
        self.assertNotIn(b'101 Switching Protocols', invalid_key_response)
        self.assertNotIn(b'101 Switching Protocols', invalid_version_response)

    def test_server_broadcasts_reload_on_screen_update(self):
        """Updating the screen must trigger a reload over WebSocket."""
        self._start_server()
        html_path = os.path.join(self.content_dir, 'style-options.html')
        with open(html_path, 'w', encoding='utf-8') as fh:
            fh.write('<div class="style-grid"><div data-choice="A">Initial</div></div>')
        time.sleep(0.3)

        ws = self._open_websocket()
        try:
            with open(html_path, 'w', encoding='utf-8') as fh:
                fh.write('<div class="style-grid"><div data-choice="B">Updated</div></div>')

            payload = json.loads(self._recv_ws_text(ws))
        finally:
            ws.close()

        self.assertEqual(payload, {'type': 'reload'})

    def test_server_clears_stale_events_when_rewriting_same_screen_file(self):
        """Reusing the same HTML for a new screen must not keep old choices."""
        self._start_server()
        html_path = os.path.join(self.content_dir, 'style-options.html')

        with open(html_path, 'w', encoding='utf-8') as fh:
            fh.write('<div class="style-grid"><div data-choice="A">Initial</div></div>')

        time.sleep(0.3)

        ws = self._open_websocket()
        try:
            self._send_ws_text(ws, json.dumps({'choice': 'A', 'label': 'Initial'}))
            time.sleep(0.2)
        finally:
            ws.close()

        events_path = os.path.join(self.state_dir, 'events')
        with open(events_path, 'r', encoding='utf-8') as fh:
            before = [line for line in fh if line.strip()]
        self.assertEqual(len(before), 1)

        with open(html_path, 'w', encoding='utf-8') as fh:
            fh.write('<div class="style-grid"><div data-choice="B">New screen</div></div>')

        time.sleep(0.4)

        with open(events_path, 'r', encoding='utf-8') as fh:
            after = [line for line in fh if line.strip()]
        self.assertEqual(after, [])


if __name__ == '__main__':
    unittest.main()
