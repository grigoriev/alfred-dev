/**
 * helper.js: WebSocket client for the Designer viewer.
 *
 * Injected as an inline script into every page that server.cjs serves.
 * Handles the WebSocket connection, the option selection by the user,
 * and the automatic reload when the server reports content changes.
 *
 * Public API on window:
 *   - window.toggleSelect(el) - Selects one option and deselects the others.
 *   - window.selectedChoice   - Last selected choice.
 *   - window.alfred           - { send(obj), choice(id, label) }
 */
(function alfredHelper() {
  'use strict';

  // -- Internal state -------------------------------------------------------

  /** @type {WebSocket|null} */
  let ws = null;

  /** @type {string|null} Last user choice. */
  let selectedChoice = null;

  /** Queue of messages sent before the socket is ready. */
  const pendingMessages = [];

  /** Reconnect timer ID. */
  let reconnectTimer = null;

  /** Retry interval in milliseconds. */
  const RECONNECT_MS = 1000;

  /**
   * Updates the connection indicator if the page has one.
   * @param {string} color
   * @param {string=} label
   */
  function setConnectionState(color, label) {
    var dot = document.getElementById('alfred-connection-dot');
    var text = document.getElementById('alfred-connection-label');
    if (dot) dot.style.background = color;
    if (text && label) text.textContent = label;
  }

  /**
   * Schedules a single reconnect attempt.
   */
  function scheduleReconnect() {
    if (reconnectTimer !== null) return;
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      connect();
    }, RECONNECT_MS);
  }

  /**
   * Flushes pending messages once the socket is open.
   */
  function flushPendingMessages() {
    while (pendingMessages.length > 0 && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(pendingMessages.shift()));
    }
  }

  // -- WebSocket connection -------------------------------------------------

  /**
   * Opens the WebSocket connection with automatic reconnect.
   * When the server sends {type:'reload'}, reloads the full page
   * to show the updated content.
   */
  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    const url = protocol + window.location.host;
    ws = new WebSocket(url);

    ws.onopen = function () {
      setConnectionState('#27ae60', 'Подключено');
      flushPendingMessages();
    };

    ws.onmessage = function (event) {
      try {
        var msg = JSON.parse(event.data);
        if (msg.type === 'reload') {
          window.location.reload();
        }
      } catch (_) {
        // Not a JSON message, ignore it
      }
    };

    ws.onclose = function () {
      ws = null;
      setConnectionState('#d97706', 'Локальный режим');
      scheduleReconnect();
    };

    ws.onerror = function () {
      // The close event fires next and retries there
    };
  }

  /**
   * Sends a user event over HTTP as a WebSocket fallback.
   * @param {object} obj
   */
  function postEvent(obj) {
    if (typeof fetch !== 'function') return Promise.resolve(false);
    return fetch('/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(obj),
      keepalive: true,
    }).then(function (response) {
      return response.ok;
    }).catch(function () {
      return false;
    });
  }

  // -- Send data to the server ---------------------------------------------

  /**
   * Sends a JSON object to the server over the WebSocket.
   * @param {object} obj - Data to send.
   */
  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
      return;
    }

    pendingMessages.push(obj);
  }

  /**
   * Records a user choice and sends it to the server.
   * @param {string} id - Option ID (for example "A", "B", "C").
   * @param {string} label - Readable option label.
   */
  function choice(id, label) {
    selectedChoice = id;
    if (ws && ws.readyState === WebSocket.OPEN) {
      send({ choice: id, label: label });
      return;
    }
    postEvent({ choice: id, label: label });
  }

  // -- Visual option selection ---------------------------------------------

  /**
   * Selects an option element and deselects its siblings.
   * Reads the data-choice attribute to identify the choice and
   * the first heading inside the element to get the readable label.
   * @param {HTMLElement} el - Element with a data-choice attribute.
   */
  function toggleSelect(el) {
    // Deselect siblings in the same container
    var parent = el.parentElement;
    if (parent) {
      var siblings = parent.querySelectorAll('[data-choice]');
      for (var i = 0; i < siblings.length; i++) {
        siblings[i].classList.remove('selected');
      }
    }

    // Select the clicked element
    el.classList.add('selected');

    var id = el.getAttribute('data-choice');
    var explicitLabel = el.getAttribute('data-label');
    var heading = el.querySelector('h1, h2, h3, h4, h5, h6');
    // Use textContent, never innerHTML, to prevent XSS if the heading
    // contains untrusted HTML.
    var label = explicitLabel || (heading ? heading.textContent : id);

    choice(id, label);

    // Update the indicator bar
    var indicator = document.getElementById('alfred-indicator');
    if (indicator) {
      indicator.textContent = 'Выбран вариант ' + label + '. Вернись в терминал, чтобы продолжить';
    }
  }

  // -- Capture clicks on options -------------------------------------------

  document.addEventListener('click', function (e) {
    var target = e.target.closest('[data-choice]');
    if (target) {
      e.preventDefault();
      toggleSelect(target);
    }
  });

  // -- Public API -----------------------------------------------------------

  Object.defineProperty(window, 'selectedChoice', {
    get: function () { return selectedChoice; },
    set: function (v) { selectedChoice = v; },
  });

  window.toggleSelect = toggleSelect;
  window.alfred = { send: send, choice: choice };

  // -- Startup --------------------------------------------------------------

  connect();
})();
