/* ── company.js — Company kanban: WS-driven board from CompanyObserver
 *
 * Connects to /api/events WS, listens for board_update events, renders
 * role cards (CEO + sub-agents) moving across 4 columns:
 *   Backlog · Running · Needs-Approval · Done
 *
 * XSS-safe: all server-provided strings go through textContent, never innerHTML.
 * ──────────────────────────────────────────────────────────────────── */

const COMPANY = (() => {
  /* ── Auth token ──────────────────────────────────────────────────── */
  let token = new URLSearchParams(location.search).get('token')
           || sessionStorage.getItem('cv_token') || '';
  if (token) {
    sessionStorage.setItem('cv_token', token);
    if (location.search.includes('token=')) {
      const u = new URL(location.href);
      u.searchParams.delete('token');
      history.replaceState(null, '', u.pathname + u.search + u.hash);
    }
  }

  function wsUrl(path) {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    return scheme + '://' + location.host + path;
  }

  /* ── Board state ─────────────────────────────────────────────────── */
  // cards: card_id → { role, column, title, subtitle, edges, el }
  const cards = new Map();

  // column div ID → DOM element cache
  const colEls = {};
  const colBadges = {};

  const COLUMNS = ['backlog', 'running', 'needs_approval', 'done'];
  const COL_LABELS = ['Backlog', 'Running', 'Needs-Approval', 'Done'];

  /* ── DOM refs ────────────────────────────────────────────────────── */
  function $(id) { return document.getElementById(id); }

  function initDOM() {
    COLUMNS.forEach(c => {
      colEls[c] = $(`col-${c}-cards`);
      // Badge is the span inside the col-hd
      const colDiv = $(`col-${c}`);
      colBadges[c] = colDiv ? colDiv.querySelector('.cmp-col-badge') : null;
    });
  }

  /* ── Render helpers ───────────────────────────────────────────────── */

  /** Escape text for safe textContent use (belt-and-suspenders). */
  function esc(s) {
    if (typeof s !== 'string') s = String(s || '');
    const d = document.createElement('div');
    d.textContent = s;
    return d.textContent;
  }

  /** Create or update a role card in a column. */
  function upsertCard(cardId, role, column, title, subtitle, edges) {
    let card = cards.get(cardId);

    if (!card) {
      // Create DOM
      card = { card_id: cardId, role, column, title, subtitle, edges: [] };
      const el = document.createElement('div');
      el.className = 'role-card';

      const roleEl = document.createElement('div');
      roleEl.className = 'rc-role' + (role === 'ceo' ? ' ceo' : '');
      el.appendChild(roleEl);

      const subEl = document.createElement('div');
      subEl.className = 'rc-subtitle';
      el.appendChild(subEl);

      const edgesEl = document.createElement('div');
      edgesEl.className = 'rc-edges';
      el.appendChild(edgesEl);

      card.el = el;
      card.roleEl = roleEl;
      card.subEl = subEl;
      card.edgesEl = edgesEl;
      cards.set(cardId, card);
    }

    // Update fields
    if (role !== undefined) card.role = role;
    if (column !== undefined && COLUMNS.includes(column)) {
      card.column = column;
    }
    if (title !== undefined) card.title = title;
    if (subtitle !== undefined) card.subtitle = subtitle;
    if (edges !== undefined) card.edges = edges;

    // Render text (textContent — XSS-safe)
    card.roleEl.textContent = esc(cardId);
    card.subEl.textContent = esc(card.subtitle || '');

    // Render edges
    card.edgesEl.textContent = '';
    if (card.edges && card.edges.length) {
      card.edges.forEach(e => {
        const span = document.createElement('span');
        span.className = 'rc-edge';
        span.textContent = esc(e.from) + ' → ' + esc(e.to);
        card.edgesEl.appendChild(span);
      });
    }

    // Done styling
    if (column === 'done') {
      card.el.classList.add('done');
    } else {
      card.el.classList.remove('done');
    }

    // Move to the right column
    const colKey = column || card.column || 'backlog';
    const targetCol = colEls[colKey];
    if (targetCol && card.el.parentNode !== targetCol) {
      targetCol.appendChild(card.el);
    }
  }

  /** Refresh all column empty-states and badge counts. */
  function refreshCounts() {
    const counts = {};
    COLUMNS.forEach(c => { counts[c] = 0; });

    cards.forEach(card => {
      const col = card.column || 'backlog';
      if (counts[col] !== undefined) counts[col]++;
    });

    COLUMNS.forEach(c => {
      const colDiv = $(`col-${c}`);
      const cardsDiv = colEls[c];
      const badge = colBadges[c];
      if (badge) badge.textContent = counts[c];

      if (counts[c] === 0 && cardsDiv) {
        cardsDiv.textContent = '';
        const empty = document.createElement('div');
        empty.className = 'cmp-col-empty';
        empty.textContent = '—';
        cardsDiv.appendChild(empty);
      } else if (cardsDiv && cardsDiv.querySelector('.cmp-col-empty')) {
        // Remove empty placeholder if we now have real cards
        const emptyEl = cardsDiv.querySelector('.cmp-col-empty');
        if (emptyEl) emptyEl.remove();
      }
    });

    $('cmp-card-count').textContent = cards.size + ' cards';
  }

  /* ── Board update handler ─────────────────────────────────────────── */

  function handleBoardUpdate(board) {
    // board is the card-op dict: { op, card_id, role, column, title, subtitle, edges }
    const op = board.op;
    const cardId = board.card_id;
    const role = board.role;
    const column = board.column;
    const title = board.title;
    const subtitle = board.subtitle;
    const edges = board.edges;

    switch (op) {
      case 'card_created':
        upsertCard(cardId, role, column, title, subtitle, edges);
        break;
      case 'card_updated':
        upsertCard(cardId, role, undefined, title, subtitle, edges);
        break;
      case 'card_moved':
        upsertCard(cardId, role, column, title, subtitle, edges);
        break;
      case 'edge_added':
        upsertCard(cardId, role, undefined, title, subtitle, edges);
        break;
      case 'card_done':
        upsertCard(cardId, role, 'done', title, subtitle, edges);
        break;
      default:
        // Unknown op — quietly ignore
        break;
    }

    refreshCounts();
    // Update badge if this was a done op
    if (op === 'card_done') {
      const c = cards.get(cardId);
      if (c && c.el) c.el.classList.add('done');
    }
  }

  /* ── WebSocket ────────────────────────────────────────────────────── */
  let ws = null;
  let reconnectTimer = null;

  function connectWS() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      ws = new WebSocket(wsUrl('/api/events'));
    } catch (e) {
      setStatus('disconnected', 'WS connection failed');
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      setStatus('connected', 'Connected — waiting for events');
      if (token) {
        try { ws.send(JSON.stringify({ type: 'auth', token })); } catch {}
      }
      $('btn-run').disabled = false;
    };

    ws.onmessage = (m) => {
      try {
        const d = JSON.parse(m.data);
        if (d.type === 'board_update' && d.board) {
          handleBoardUpdate(d.board);
        }
        // Also listen for incoming_call, task_update — just for awareness
      } catch {}
    };

    ws.onclose = () => {
      setStatus('disconnected', 'WS closed — reconnecting...');
      $('btn-run').disabled = true;
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose fires after onerror, so reconnect is handled there
      setStatus('disconnected', 'WS error');
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      connectWS();
    }, 2000);
  }

  function setStatus(state, text) {
    const dot = $('cmp-dot');
    dot.className = 'live-dot' + (state === 'connected' ? ' connected' : '');
    $('cmp-status-text').textContent = text;
    $('cmp-hd-badge').textContent = state === 'connected' ? 'Live' : 'Disconnected';
  }

  /* ── API: POST /api/company/run ──────────────────────────────────── */
  async function postRun() {
    const btn = $('btn-run');
    btn.disabled = true;
    btn.textContent = 'Running...';
    showToast('Starting company run...');

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['x-cv-token'] = token;
      const r = await fetch('/api/company/run', {
        method: 'POST',
        headers,
      });
      const data = await r.json();
      if (r.ok) {
        showToast('Run started: ' + data.run_id + ' (fixture: ' + data.fixture_mode + ')');
      } else {
        showToast('Error: ' + (data.error || data.detail || 'Unknown error'));
      }
    } catch (e) {
      showToast('Fetch error: ' + (e && e.message ? e.message : e));
    } finally {
      btn.disabled = false;
      btn.textContent = 'Run Demo';
    }
  }

  function resetBoard() {
    cards.forEach(card => {
      if (card.el && card.el.parentNode) card.el.parentNode.removeChild(card.el);
    });
    cards.clear();
    COLUMNS.forEach(c => {
      const div = colEls[c];
      if (div) {
        div.textContent = '';
        const empty = document.createElement('div');
        empty.className = 'cmp-col-empty';
        empty.textContent = '—';
        div.appendChild(empty);
      }
      if (colBadges[c]) colBadges[c].textContent = '0';
    });
    $('cmp-card-count').textContent = '0 cards';
  }

  /* ── Toast ────────────────────────────────────────────────────────── */
  let toastTimer = null;
  function showToast(msg) {
    const el = $('cmp-toast');
    el.textContent = msg;
    el.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.classList.remove('show'); }, 3500);
  }

  /* ── Init ─────────────────────────────────────────────────────────── */
  function init() {
    initDOM();
    $('btn-run').addEventListener('click', postRun);
    $('btn-reset').addEventListener('click', resetBoard);
    connectWS();
  }

  window.addEventListener('DOMContentLoaded', init);

  return { cards: () => cards, reset: resetBoard, postRun };
})();
