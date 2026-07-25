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
           || document.querySelector('meta[name="cv-company-capability"]')?.content
           || window.__CV_COMPANY_CAPABILITY__
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
  let networkState = { version: 1, user_avatar: '/static/assets/yellow-sheep-meditating.png', nodes: [], edges: [], activity: [] };
  let activeCompany = null;

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

  function authHeaders(json = false) {
    const headers = {};
    if (json) headers['Content-Type'] = 'application/json';
    if (token) headers['x-cv-token'] = token;
    return headers;
  }

  function populatePicker(picker, presets, selectedId) {
    if (!picker) return;
    picker.replaceChildren();
    presets.forEach(preset => {
      const option = document.createElement('option');
      option.value = preset.id;
      option.textContent = preset.name;
      option.selected = preset.id === selectedId;
      picker.appendChild(option);
    });
    picker.disabled = false;
  }

  function renderCompanyState(payload) {
    const state = payload && (payload.company || payload);
    if (!state || !state.active) return;
    activeCompany = state.active;
    const picker = $('company-picker');
    const companyPresets = state.company_presets || state.presets || [];
    const teamPresets = state.team_presets || [];
    if (picker && Array.isArray(companyPresets)) {
      populatePicker(picker, companyPresets, activeCompany.company_preset_id || activeCompany.preset_id);
      picker.title = activeCompany.tagline || activeCompany.name;
    }
    const teamPicker = $('team-picker');
    if (teamPicker && Array.isArray(teamPresets)) {
      populatePicker(teamPicker, teamPresets, activeCompany.team_preset_id);
      teamPicker.title = activeCompany.team_name || 'Selected employee team';
    }
    const roleNames = (activeCompany.role_profiles || []).map(role => role.label || role.id);
    const teamLabel = activeCompany.team_name || 'Employee team';
    const summary = $('company-team-summary');
    if (summary) summary.textContent = `${teamLabel} · ${roleNames.join(' · ')}`;
    const boardSubtitle = $('company-board-subtitle');
    if (boardSubtitle) boardSubtitle.textContent = `${activeCompany.name} / ${teamLabel} · ${roleNames.join(' · ')}`;
    const networkSubtitle = $('network-subtitle');
    if (networkSubtitle) networkSubtitle.textContent = `You → Yellow Sheep CS → ${activeCompany.name} CEO → ${teamLabel}`;
  }

  async function loadCompanyState() {
    try {
      const response = await fetch('/api/company/active', { headers: authHeaders() });
      if (!response.ok) return;
      renderCompanyState(await response.json());
      // The idle network is not an empty state: it is the selected company
      // plus its roster.  Hydrate it immediately so a refresh never leaves
      // the user looking at only You → CS → CEO until a task is dispatched.
      await syncCompanyState();
    } catch {}
  }

  async function selectCompanyPreset(event) {
    const picker = event.currentTarget;
    const previousPreset = activeCompany && (activeCompany.company_preset_id || activeCompany.preset_id);
    const presetId = picker.value;
    if (!presetId || presetId === previousPreset) return;
    picker.disabled = true;
    try {
      const response = await fetch('/api/company/active', {
        method: 'PUT',
        headers: authHeaders(true),
        body: JSON.stringify({ company_preset_id: presetId }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.error || 'Could not switch company');
      renderCompanyState(data);
      resetBoard();
      networkState = { version: 1, user_avatar: data.active?.avatar || networkState.user_avatar, nodes: [], edges: [], activity: [] };
      renderNetwork();
      showToast(`Switched to ${data.active.name}. Yellow Sheep now routes to its CEO and team.`);
      await syncCompanyState();
    } catch (error) {
      if (previousPreset) picker.value = previousPreset;
      showToast('Company switch failed: ' + (error.message || error));
    } finally {
      picker.disabled = false;
    }
  }

  async function selectTeamPreset(event) {
    const picker = event.currentTarget;
    const previousPreset = activeCompany && activeCompany.team_preset_id;
    const presetId = picker.value;
    if (!presetId || presetId === previousPreset) return;
    picker.disabled = true;
    try {
      const response = await fetch('/api/company/team', {
        method: 'PUT',
        headers: authHeaders(true),
        body: JSON.stringify({ team_preset_id: presetId }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.error || 'Could not switch employee team');
      renderCompanyState(data);
      resetBoard();
      networkState = { version: 1, user_avatar: data.active?.avatar || networkState.user_avatar, nodes: [], edges: [], activity: [] };
      renderNetwork();
      showToast(`Employee team switched to ${data.active.team_name}. Yellow Sheep will use it for the next handoff.`);
      await syncCompanyState();
    } catch (error) {
      if (previousPreset) picker.value = previousPreset;
      showToast('Employee team switch failed: ' + (error.message || error));
    } finally {
      picker.disabled = false;
    }
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
      setPetMood('celebration mode · the crew shipped a milestone', true);
    }
  }

  function handleNetworkUpdate(payload) {
    const snapshot = payload && (payload.snapshot || payload.network || payload);
    if (!snapshot || !Array.isArray(snapshot.nodes)) return;
    networkState = snapshot;
    renderNetwork();
  }

  function renderNetwork() {
    const graph = $('network-graph');
    const edgeSvg = $('network-edges');
    if (!graph || !edgeSvg) return;
    graph.querySelectorAll('.network-node').forEach(el => el.remove());
    edgeSvg.replaceChildren();
    const nodes = networkState.nodes || [];
    const agents = nodes.filter(n => n.kind === 'agent');
    const narrow = window.matchMedia('(max-width: 560px)').matches;
    const parent = graph.closest('.network-panel');
    const manyAgents = agents.length > 4;
    graph.classList.toggle('network-many', manyAgents);
    if (parent) parent.classList.toggle('network-many', manyAgents);

    // The chain is intentionally vertical, like a small organisation chart:
    // caller → CS → CEO → specialist team.  This avoids the unreadable
    // left-to-right collision the earlier network view produced.
    const positions = narrow
      ? { user: [50, 9], cs: [50, 31], ceo: [50, 53] }
      : { user: [50, 12], cs: [50, 38], ceo: [50, 64] };
    const agentXs = agents.length === 1 ? [50]
      : agents.length === 2 ? [32, 68]
      : agents.length === 3 ? [20, 50, 80]
      : [14, 38, 62, 86];
    agents.forEach((node, index) => {
      if (!manyAgents) {
        positions[node.id] = [agentXs[index], narrow ? (agents.length > 2 ? 76 + Math.floor(index / 2) * 17 : 80) : 88];
        if (narrow && agents.length > 2) positions[node.id][0] = index % 2 ? 70 : 30;
      } else {
        positions[node.id] = [index % 3 === 0 ? 20 : index % 3 === 1 ? 50 : 80, 79 + Math.floor(index / 3) * 15];
      }
    });

    const svgPoint = (id, direction) => {
      const point = positions[id] || [50, 50];
      // Cards are centred at their coordinates; an 86-unit offset keeps the
      // connector in the clean space between cards rather than behind labels.
      return [point[0] * 10, (point[1] + (direction === 'down' ? 8.6 : -8.6)) * 10];
    };
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', 'network-arrow'); marker.setAttribute('viewBox', '0 0 10 10'); marker.setAttribute('refX', '8'); marker.setAttribute('refY', '5'); marker.setAttribute('markerWidth', '5'); marker.setAttribute('markerHeight', '5'); marker.setAttribute('orient', 'auto-start-reverse');
    const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path'); arrow.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z'); arrow.setAttribute('fill', '#71909a'); marker.appendChild(arrow); defs.appendChild(marker); edgeSvg.appendChild(defs);
    (networkState.edges || []).forEach(edge => {
      const from = positions[edge.from]; const to = positions[edge.to];
      if (!from || !to) return;
      const down = to[1] >= from[1];
      const a = svgPoint(edge.from, down ? 'down' : 'up');
      const b = svgPoint(edge.to, down ? 'up' : 'down');
      const midY = Math.round((a[1] + b[1]) / 2);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', `M ${a[0]} ${a[1]} V ${midY} H ${b[0]} V ${b[1]}`);
      path.setAttribute('marker-end', 'url(#network-arrow)');
      path.setAttribute('class', `network-edge-line edge-${edge.kind || 'message'}${edge.status === 'active' ? ' active' : ''}`);
      edgeSvg.appendChild(path);
    });
    nodes.forEach(node => {
      const p = positions[node.id] || [52, 50];
      const el = document.createElement('div');
      el.className = `network-node kind-${node.kind || 'agent'} ${node.status || 'idle'}`;
      el.style.left = p[0] + '%'; el.style.top = p[1] + '%';
      const avatar = document.createElement('div'); avatar.className = 'nn-avatar';
      const avatarSrc = node.avatar || (node.kind === 'user' ? networkState.user_avatar : node.kind === 'cs' ? '/static/assets/yellow-sheep-meditating.png' : '');
      if (avatarSrc) {
        const img = document.createElement('img'); img.alt = node.label || node.id; img.src = avatarSrc;
        img.onerror = () => { avatar.textContent = (node.label || node.id).slice(0, 2).toUpperCase(); };
        avatar.appendChild(img);
      } else {
        avatar.textContent = (node.label || node.id).split(/\s+/).map(word => word[0]).join('').slice(0, 2).toUpperCase();
      }
      const label = document.createElement('div'); label.className = 'nn-label'; label.textContent = node.label || node.id;
      const status = document.createElement('div'); status.className = 'nn-status'; status.textContent = node.status || 'idle';
      const summary = document.createElement('div'); summary.className = 'nn-summary'; summary.textContent = node.summary || '';
      el.append(avatar, label, status, summary); graph.appendChild(el);
    });
    const empty = $('network-empty'); if (empty) empty.style.display = nodes.length ? 'none' : '';
    const activity = $('network-activity');
    if (activity) {
      activity.replaceChildren();
      const items = (networkState.activity || []).slice(-5).reverse();
      if (!items.length) { const e = document.createElement('div'); e.className = 'network-empty'; e.textContent = 'Internal summaries will appear here as agents communicate.'; activity.appendChild(e); }
      items.forEach(item => { const row = document.createElement('div'); row.className = 'na-row'; const arrow = document.createElement('span'); arrow.className = 'na-arrow'; arrow.textContent = `${item.from || '?'} → ${item.to || '?'}`; row.appendChild(arrow); const text = document.createElement('span'); text.className = 'na-text'; text.textContent = item.text || item.kind || ''; row.appendChild(text); activity.appendChild(row); });
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
      syncCompanyState();
    };

    ws.onmessage = (m) => {
      try {
        const d = JSON.parse(m.data);
        if (d.type === 'board_update' && d.board) {
          handleBoardUpdate(d.board);
        }
        if (d.type === 'network_update') handleNetworkUpdate(d);
        // Also listen for incoming_call, task_update — just for awareness
      } catch {}
    };

    ws.onclose = () => {
      setStatus('disconnected', 'WS closed — reconnecting...');
      // The demo endpoint is HTTP and remains usable while the live event
      // socket reconnects (or when the page is opened without a token).
      $('btn-run').disabled = false;
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

  /* Hydrate cards for a board opened after a run already started. */
  async function syncCompanyState() {
    try {
      const r = await fetch('/api/company', { headers: authHeaders() });
      if (!r.ok) return;
      const data = await r.json();
      if (data.company) renderCompanyState(data.company);
      const ops = data.emitted_ops || [];
      ops.forEach(handleBoardUpdate);
      if (data.network) handleNetworkUpdate(data.network);
      if (data.status === 'running') setStatus('connected', `Live — run ${data.run_id || 'in progress'}`);
    } catch {}
  }

  /* ── API: POST /api/company/run ──────────────────────────────────── */
  async function postRun() {
    const btn = $('btn-run');
    btn.disabled = true;
    btn.textContent = 'Running...';
    showToast('Starting company run...');

    try {
      const r = await fetch('/api/company/run', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({}),
      });
      const data = await r.json();
      if (r.ok) {
        showToast(`Run started: ${data.run_id} · ${data.backend}${data.fixture_mode ? ' fixture' : ''}`);
      } else {
        showToast('Error: ' + (data.error || data.detail || 'Unknown error'));
      }
    } catch (e) {
      showToast('Fetch error: ' + (e && e.message ? e.message : e));
    } finally {
      btn.disabled = false;
      btn.textContent = 'Run Team';
    }
  }

  async function uploadAvatar(file) {
    if (!file || !/^image\/(png|jpeg|gif|webp)$/.test(file.type) || file.size > 5 * 1024 * 1024) {
      showToast('Choose a PNG, JPEG, GIF, or WebP image under 5 MB.');
      return;
    }
    try {
      const headers = { 'Content-Type': file.type }; if (token) headers['x-cv-token'] = token;
      const response = await fetch('/api/company/avatar', { method: 'POST', headers, body: file });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.error || 'Upload failed');
      networkState.user_avatar = data.avatar_url;
      networkState.nodes = (networkState.nodes || []).map(n => n.id === 'user' ? { ...n, avatar: data.avatar_url } : n);
      renderNetwork(); showToast('Avatar uploaded locally.');
    } catch (error) { showToast('Avatar upload failed: ' + (error.message || error)); }
  }

  async function generateAvatar() {
    const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 256;
    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 256, 256); gradient.addColorStop(0, '#e3ae45'); gradient.addColorStop(1, '#6f9aad');
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, 256, 256); ctx.fillStyle = '#182735'; ctx.font = '700 76px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('YOU', 128, 128);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    if (blob) await uploadAvatar(new File([blob], 'you.png', { type: 'image/png' }));
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

  let petMoodEl = null;
  let petButtonEl = null;
  let petImageEl = null;
  function setPetMood(text, bounce = false, imageName = '') {
    if (petMoodEl) petMoodEl.textContent = text;
    if (petImageEl && imageName) {
      petImageEl.src = `/static/assets/${imageName}`;
    }
    if (bounce && petButtonEl) {
      petButtonEl.classList.remove('pet-bounce');
      // Force a reflow so repeated board events still feel interactive.
      void petButtonEl.offsetWidth;
      petButtonEl.classList.add('pet-bounce');
    }
  }

  /* ── Init ─────────────────────────────────────────────────────────── */
  function init() {
    initDOM();
    $('btn-run').addEventListener('click', postRun);
    $('btn-reset').addEventListener('click', resetBoard);
    const companyPicker = $('company-picker');
    if (companyPicker) companyPicker.addEventListener('change', selectCompanyPreset);
    const teamPicker = $('team-picker');
    if (teamPicker) teamPicker.addEventListener('change', selectTeamPreset);
    $('btn-run').disabled = false;
    connectWS();
    renderNetwork();
    loadCompanyState();
    const avatarInput = $('network-avatar-upload');
    if (avatarInput) avatarInput.addEventListener('change', event => uploadAvatar(event.target.files && event.target.files[0]));
    const avatarGenerate = $('network-avatar-generate');
    if (avatarGenerate) avatarGenerate.addEventListener('click', generateAvatar);

    petMoodEl = $('pet-mood');
    petButtonEl = $('pet-button');
    petImageEl = petButtonEl ? petButtonEl.querySelector('img') : null;
    if (petButtonEl) {
      const moods = [
        'waiting by the lighthouse',
        'mapping a route through the mountains',
        '船已准备好 · ready to build',
        'watching the crew ship something useful',
      ];
      let moodIndex = 0;
      petButtonEl.addEventListener('click', () => {
        moodIndex = (moodIndex + 1) % moods.length;
        setPetMood(moods[moodIndex], true);
      });
    }

    /* Voice and board share one surface: a dispatch event is reflected in
     * the transcript immediately, while the backend's board_update events
     * populate the role cards below. */
    if (window.VoiceControl) {
      const statusEl = $('voice-status');
      const statusTextEl = $('voice-status-text');
      const callBtn = $('voice-call');
      const muteBtn = $('voice-mute');
      const hangupBtn = $('voice-hangup');
      const transcriptEl = $('voice-transcript-text');
      const logEl = $('voice-log');
      const voice = new VoiceControl({
        token,
        onStatus: (state, text) => {
          statusEl.className = `voice-status ${state}`;
          statusTextEl.textContent = text;
          callBtn.disabled = state === 'connecting' || state === 'connected' || state === 'muted';
          muteBtn.disabled = !(state === 'connected' || state === 'muted');
          hangupBtn.disabled = !(state === 'connecting' || state === 'connected' || state === 'muted');
          muteBtn.textContent = state === 'muted' ? 'Unmute' : 'Mute';
          const moods = {
            idle: 'waiting by the lighthouse',
            connecting: 'tuning the radio to your voice',
            connected: 'listening for your next move',
            muted: 'quiet mode · still watching the board',
            error: 'the signal dropped · tap Call to try again',
          };
          const petAsset = (state === 'idle' || state === 'muted') ? 'yellow-sheep-meditating.png' : 'yellow-sheep-hero.png';
          setPetMood(moods[state] || 'keeping watch over the company', state === 'connected', petAsset);
        },
        onTranscript: (text) => { transcriptEl.textContent = text; },
        onLog: (text) => {
          const row = document.createElement('div');
          row.textContent = `${new Date().toLocaleTimeString([], { hour12: false })}  ${text}`;
          logEl.appendChild(row);
          while (logEl.children.length > 40) logEl.firstChild.remove();
          logEl.scrollTop = logEl.scrollHeight;
        },
        onDispatched: (data) => {
          const task = data.task || 'Task dispatched';
          transcriptEl.textContent = `工程师已接单：${task}`;
          showToast(`Engineer team accepted: ${task}`);
          setPetMood('happy hooves · the crew is on it', true);
          syncCompanyState();
        },
        onAgentState: (data) => {
          const state = data.state || 'listening';
          const moods = {
            dispatching: ['passing your brief to the CEO team', 'yellow-sheep-hero.png'],
            listening: ['listening for your next move', 'yellow-sheep-hero.png'],
            ending: ['waving goodbye from the lighthouse', 'yellow-sheep-meditating.png'],
          };
          const [mood, asset] = moods[state] || moods.listening;
          setPetMood(mood, state === 'dispatching', asset);
        },
      });
      callBtn.addEventListener('click', async () => {
        try { await voice.connect(); } catch {}
      });
      muteBtn.addEventListener('click', () => voice.toggleMute());
      hangupBtn.addEventListener('click', () => voice.hangUp());
      voice.onLog('Voice Control ready — board and call are connected.');
    }

    // Keep the board accurate when a judge opens it after the first event.
    setInterval(syncCompanyState, 4000);
  }

  window.addEventListener('DOMContentLoaded', init);

  return { cards: () => cards, reset: resetBoard, postRun };
})();
