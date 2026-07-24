/* ── call.js — CV state machine + mock backend ─────────────────────────
 *
 * State: idle → dialing → in-call → (incoming/ended) → idle
 *
 * All backend calls are funnelled through CV.api so the real WS can
 * replace this object without touching any UI code.
 * ──────────────────────────────────────────────────────────────────── */

const CV = (() => {
  /* ── Auth pass-through ─────────────────────────────────────────── */
  const token = new URLSearchParams(location.search).get('token') || '';

  /* ══════════════════════════════════════════════════════════════════
   * MOCK BACKEND  (swap to real WS — see comment on each method)
   * ══════════════════════════════════════════════════════════════════ */
  const api = {

    /* connectCall()
     * Real: open WS /api/call?token=…  (binary PCM16 each way)
     * Mock: resolve after 1.2 s, start driving a fake waveform array   */
    async connectCall() {
      await delay(1200);
      return { ok: true, channel: 'mock' };
    },

    /* events()
     * Real: open WS /api/events?token=…  push JSON events
     * Mock: keep a listener map; call simulateIncomingCall(reason)
     *       to fire one. Also auto-fire a sample incoming_call ~6 s
     *       after the call goes in-call (demo hook).                  */
    events() {
      const listeners = [];
      const sub = {
        on: (evt, fn) => listeners.push({ evt, fn }),
        off: (evt, fn) {},
        close() { listeners.length = 0; },
      };
      // expose global for demo
      window.CV = window.CV || {};
      window.CV.simulateIncomingCall = (reason) => {
        listeners.filter(l => l.evt === 'incoming_call').forEach(l => l.fn({ reason }));
      };
      return sub;
    },

    /* board()
     * Real: GET /api/board  (token via x-cv-token header, not the URL query,
     *       so it doesn't leak into logs/Referer)
     * Mock: return static sample data; never fails so kanban is never empty */
    async board() {
      try {
        const r = await fetch('/api/board', {
          headers: token ? { 'x-cv-token': token } : {},
        });
        if (r.ok) return r.json();
      } catch {}
      return sampleBoard();
    },

    /* hangUp() */
    async hangUp() {
      await delay(300);
      return { ok: true };
    },
  };

  /* ── Sample kanban data ─────────────────────────────────────────── */
  function sampleBoard() {
    return {
      pending: [
        { task_id: 't-001', description: 'Refactor auth middleware', progress_pct: 0, status: 'pending', files_changed: [] },
        { task_id: 't-002', description: 'Add unit tests for dispatch', progress_pct: 0, status: 'pending', files_changed: [] },
      ],
      in_progress: [
        { task_id: 't-003', description: 'Optimize board polling interval', progress_pct: 45, status: 'running', files_changed: ['api/board.js'] },
      ],
      done: [
        { task_id: 't-004', description: 'Wire up WebSocket connection', progress_pct: 100, status: 'completed', files_changed: ['call.js', 'call.css'] },
        { task_id: 't-005', description: 'Create state machine skeleton', progress_pct: 100, status: 'completed', files_changed: ['call.js'] },
      ],
      updated_at: Date.now(),
    };
  }

  /* ══════════════════════════════════════════════════════════════════
   * SYNTHESIZED RINGTONE  (WebAudio — no asset needed)
   * Two ascending tones: C5 → E5, 450 ms each, 100 ms gap, repeat × 3
   * ══════════════════════════════════════════════════════════════════ */
  let ringCtx = null;
  function playRingtone() {
    stopRingtone();
    ringCtx = new (window.AudioContext || window.webkitAudioContext)();
    const schedule = () => {
      [523.25, 659.25].forEach((freq, i) => {
        const o  = ringCtx.createOscillator();
        const g  = ringCtx.createGain();
        o.connect(g); g.connect(ringCtx.destination);
        o.type = 'sine';
        o.frequency.value = freq;
        const t = ringCtx.currentTime + i * 0.6;
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(0.35, t + 0.04);
        g.gain.exponentialRampToValueAtTime(0.001, t + 0.44);
        o.start(t); o.stop(t + 0.46);
      });
    };
    schedule();
    ringCtx._ringTimer = setInterval(schedule, 2200);
  }
  function stopRingtone() {
    if (ringCtx?._ringTimer) { clearInterval(ringCtx._ringTimer); ringCtx._ringTimer = null; }
    ringCtx = null;
  }

  /* ══════════════════════════════════════════════════════════════════
   * WAVEFORM  (mock in-call audio level meter)
   * Real: PCM binary from WS; Mock: semi-random amplitudes
   * ══════════════════════════════════════════════════════════════════ */
  const BARS = 44;
  let wfTimer = null;
  let wfAmps = Array.from({ length: BARS }, () => 0.2);

  function startWaveform() {
    wfAmps = Array.from({ length: BARS }, () => Math.random() * 0.15 + 0.05);
    wfTimer = setInterval(() => {
      wfAmps = wfAmps.map((_, i) => {
        const target = Math.random() * 0.85 + 0.05;
        return wfAmps[i] + (target - wfAmps[i]) * 0.35;
      });
      renderWaveform();
    }, 80);
  }
  function stopWaveform() {
    if (wfTimer) { clearInterval(wfTimer); wfTimer = null; }
    wfAmps = Array.from({ length: BARS }, () => 0.05);
    renderWaveform();
  }

  /* ══════════════════════════════════════════════════════════════════
   * KANBAN  (poll every 2 s)
   * ══════════════════════════════════════════════════════════════════ */
  let boardTimer = null;
  let boardData = sampleBoard();

  async function startBoardPoll() {
    boardTimer = setInterval(async () => {
      try {
        boardData = await api.board();
      } catch { boardData = sampleBoard(); }
      renderBoard();
    }, 2000);
  }
  function stopBoardPoll() {
    if (boardTimer) { clearInterval(boardTimer); boardTimer = null; }
  }

  /* ══════════════════════════════════════════════════════════════════
   * STATE MACHINE
   * ══════════════════════════════════════════════════════════════════ */
  let state = 'idle';
  let eventsSub = null;
  let incomingReason = '';
  let callStartMs  = 0;
  let autoIncomingTimer = null;   // demo: fires ~6 s after in-call

  const transition = (newState) => {
    exitState(state);
    state = newState;
    enterState(newState);
  };

  function exitState(s) {
    if (s === 'in-call') {
      stopWaveform();
      stopBoardPoll();
      stopRingtone();
      if (autoIncomingTimer) { clearTimeout(autoIncomingTimer); autoIncomingTimer = null; }
    }
    if (s === 'incoming') stopRingtone();
  }

  async function enterState(s) {
    hideAllViews();
    document.getElementById(`view-${s}`).classList.add('active');

    switch (s) {
      case 'dialing': {
        // connect backend, then go in-call
        try { await api.connectCall(); } catch {}
        transition('in-call');
        break;
      }
      case 'in-call': {
        callStartMs = Date.now();
        startWaveform();
        startBoardPoll();
        renderBoard();
        // demo hook: auto-fire an incoming_call 6 s into the call
        autoIncomingTimer = setTimeout(() => {
          if (state === 'in-call') {
            // Simulate the agent calling you back
            window.CV.simulateIncomingCall('任务完成，需要您确认方案');
          }
        }, 6000);
        break;
      }
      case 'incoming': {
        playRingtone();
        break;
      }
      case 'ended': {
        stopWaveform(); stopBoardPoll(); stopRingtone();
        document.getElementById('ended-dur').textContent =
          formatDuration(Date.now() - callStartMs);
        setTimeout(() => transition('idle'), 2200);
        break;
      }
    }
  }

  /* ══════════════════════════════════════════════════════════════════
   * INIT  (wire events channel on idle → incoming)
   * ══════════════════════════════════════════════════════════════════ */
  function init() {
    // Attach listeners
    document.getElementById('btn-call')   .addEventListener('click', () => transition('dialing'));
    document.getElementById('btn-mute')   .addEventListener('click', toggleMute);
    document.getElementById('btn-hangup') .addEventListener('click', hangUp);
    document.getElementById('btn-accept') .addEventListener('click', acceptIncoming);
    document.getElementById('btn-decline').addEventListener('click', declineIncoming);
    document.getElementById('btn-ended-back').addEventListener('click', () => transition('idle'));

    eventsSub = api.events();
    eventsSub.on('incoming_call', ({ reason }) => {
      if (state === 'in-call') {
        incomingReason = reason;
        transition('incoming');
      }
    });

    transition('idle');
  }

  function hangUp() {
    api.hangUp();
    transition('ended');
  }

  function acceptIncoming() {
    stopRingtone();
    transition('in-call');
  }

  function declineIncoming() {
    stopRingtone();
    transition('ended');
  }

  let muted = false;
  function toggleMute() {
    muted = !muted;
    document.getElementById('btn-mute').classList.toggle('active', muted);
  }

  /* ══════════════════════════════════════════════════════════════════
   * RENDER HELPERS
   * ══════════════════════════════════════════════════════════════════ */
  function renderWaveform() {
    const strip = document.getElementById('wf-strip');
    if (!strip) return;
    strip.innerHTML = '';
    const len = wfAmps.length;
    wfAmps.forEach((a, i) => {
      const bar = document.createElement('div');
      bar.className = 'wave-bar';
      bar.style.height = (a * 100).toFixed(1) + '%';
      bar.style.opacity = 0.55 + a * 0.45;
      strip.appendChild(bar);
    });
  }

  function renderBoard() {
    const d = boardData;
    renderCol('pending',   d.pending   || []);
    renderCol('inProgress',d.in_progress || []);
    renderCol('done',      d.done      || []);
  }

  function renderCol(id, tasks) {
    const col   = document.getElementById(`col-${id}`);
    const count = document.getElementById(`cnt-${id}`);
    if (!col) return;
    count.textContent = tasks.length;
    if (!tasks.length) { col.innerHTML = '<div class="col-empty">—</div>'; return; }
    col.innerHTML = tasks.map(t => `
      <div class="task-card${t.status === 'completed' ? ' done' : ''}">
        <div class="tc-id">#${esc(t.task_id)}</div>
        <div class="tc-msg">${esc(t.description || t.latest_message || '')}</div>
        <div class="tc-bar"><div class="tc-fill" style="width:${Math.max(0, Math.min(100, Number(t.progress_pct) || 0))}%"></div></div>
      </div>`).join('');
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function hideAllViews() {
    ['idle', 'dialing', 'in-call', 'incoming', 'ended'].forEach(s => {
      document.getElementById(`view-${s}`)?.classList.remove('active');
    });
  }

  function formatDuration(ms) {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${r.toString().padStart(2, '0')}`;
  }

  function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

  /* ══════════════════════════════════════════════════════════════════
   * BOOTSTRAP  (after DOMContentLoaded)
   * ══════════════════════════════════════════════════════════════════ */
  window.addEventListener('DOMContentLoaded', init);

  // Expose api for inspection / console use
  return { api, state: () => state };
})();
