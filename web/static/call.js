/* ── call.js — CV state machine + mock backend ─────────────────────────
 *
 * State: idle → dialing → in-call → (incoming/ended) → idle
 *
 * All backend calls are funnelled through CV.api so the real WS can
 * replace this object without touching any UI code.
 * ──────────────────────────────────────────────────────────────────── */

const CV = (() => {
  /* ── Auth token ────────────────────────────────────────────────────
   * Arrives once via ?token= (opening a link on your phone). We stash it in
   * sessionStorage and STRIP it from the visible URL so it isn't bookmarked
   * or leaked further. It's sent to APIs via the x-cv-token header (fetch) or
   * as the first WS message (auth) — never in a WS URL / access log. */
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

  /* ── WS URL helper (NO token in the URL — sent as first message) ── */
  function wsUrl(path) {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${scheme}://${location.host}${path}`;
  }

  /* ══════════════════════════════════════════════════════════════════
   * REAL AUDIO ENGINE  (mic → PCM16 24k → WS /api/call → playback)
   * StepFun stepaudio-2.5-realtime: 24 kHz mono PCM16 both ways.
   * ══════════════════════════════════════════════════════════════════ */
  const RATE = 24000;
  const rt = {
    active: false, muted: false, level: 0,
    ws: null, ctx: null, micStream: null, node: null, src: null, sink: null,
    playHead: 0, playing: [],

    async start() {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC({ sampleRate: RATE });
      await this.ctx.resume();                       // iOS: must follow a tap
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      // Open the bridge WS and wait for it to be ready.
      this.ws = new WebSocket(wsUrl('/api/call'));
      this.ws.binaryType = 'arraybuffer';
      await new Promise((res, rej) => {
        this.ws.onopen = res;
        this.ws.onerror = () => rej(new Error('call WS error'));
        setTimeout(() => rej(new Error('call WS timeout')), 8000);
      });
      // First message must be auth (server validates before processing audio).
      if (token) this.ws.send(JSON.stringify({ type: 'auth', token }));
      this.ws.onmessage = (m) => this._onServer(m);
      this.ws.onclose = () => { this.active = false; };
      // Capture graph: mic → ScriptProcessor → zero-gain sink (no echo).
      this.src = this.ctx.createMediaStreamSource(this.micStream);
      this.node = this.ctx.createScriptProcessor(4096, 1, 1);
      this.sink = this.ctx.createGain(); this.sink.gain.value = 0;
      this.src.connect(this.node); this.node.connect(this.sink); this.sink.connect(this.ctx.destination);
      this.node.onaudioprocess = (e) => this._onMic(e);
      this.inRate = this.ctx.sampleRate || RATE;   // iOS may force 48k despite the hint
      this.playHead = this.ctx.currentTime;
      this.active = true;
    },

    _onMic(e) {
      const inb = e.inputBuffer.getChannelData(0);
      // level for the waveform
      let sum = 0; for (let i = 0; i < inb.length; i++) sum += inb[i] * inb[i];
      this.level = Math.min(1, Math.sqrt(sum / inb.length) * 4);
      if (this.muted || !this.ws || this.ws.readyState !== 1) return;
      // Resample to 24 kHz if the context isn't already there (iOS often is 48k).
      let samples = inb;
      if (this.inRate !== RATE) {
        const ratio = RATE / this.inRate;
        const outLen = Math.round(inb.length * ratio);
        const out = new Float32Array(outLen);
        for (let i = 0; i < outLen; i++) {
          const src = i / ratio;
          const i0 = Math.floor(src), i1 = Math.min(i0 + 1, inb.length - 1);
          const frac = src - i0;
          out[i] = inb[i0] * (1 - frac) + inb[i1] * frac;
        }
        samples = out;
      }
      const pcm = new Int16Array(samples.length);
      for (let i = 0; i < samples.length; i++) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      try { this.ws.send(pcm.buffer); } catch {}
    },

    _onServer(m) {
      if (typeof m.data === 'string') {
        try {
          const d = JSON.parse(m.data);
          if (d.type === 'barge-in') this._flush();   // stop playback, user is talking
        } catch {}
        return;
      }
      const i16 = new Int16Array(m.data);
      const f32 = new Float32Array(i16.length);
      for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 0x8000;
      const buf = this.ctx.createBuffer(1, f32.length, RATE);
      buf.copyToChannel(f32, 0);
      const src = this.ctx.createBufferSource();
      src.buffer = buf; src.connect(this.ctx.destination);
      const now = this.ctx.currentTime;
      const t = Math.max(now + 0.02, this.playHead);
      src.start(t); this.playHead = t + buf.duration;
      this.playing.push(src);
      src.onended = () => { this.playing = this.playing.filter(s => s !== src); };
    },

    _flush() {
      this.playing.forEach(s => { try { s.stop(); } catch {} });
      this.playing = [];
      this.playHead = this.ctx ? this.ctx.currentTime : 0;
    },

    stop() {
      this.active = false;
      try { this.node && (this.node.onaudioprocess = null); } catch {}
      try { this.src && this.src.disconnect(); } catch {}
      try { this.node && this.node.disconnect(); } catch {}
      try { this.sink && this.sink.disconnect(); } catch {}
      try { this.micStream && this.micStream.getTracks().forEach(t => t.stop()); } catch {}
      this._flush();
      try { this.ws && this.ws.close(); } catch {}
      try { this.ctx && this.ctx.close(); } catch {}
      this.ws = null; this.ctx = null; this.micStream = null; this.node = null;
    },
  };

  /* ══════════════════════════════════════════════════════════════════
   * BACKEND  (real WS with graceful mock fallback)
   * ══════════════════════════════════════════════════════════════════ */
  const api = {

    /* connectCall() → open the real StepFun voice bridge; fall back to mock. */
    async connectCall() {
      try {
        await rt.start();
        return { ok: true, channel: 'stepfun' };
      } catch (e) {
        console.warn('[CV] real audio unavailable, using mock:', e && e.message);
        rt.active = false;
        await delay(800);
        return { ok: true, channel: 'mock' };
      }
    },

    /* events() → real WS /api/events (server can ring you); demo hook kept. */
    events() {
      const listeners = [];
      const emit = (evt, data) =>
        listeners.filter(l => l.evt === evt).forEach(l => l.fn(data));
      const sub = {
        on: (evt, fn) => listeners.push({ evt, fn }),
        off() {},
        close() { try { sub._ws && sub._ws.close(); } catch {} listeners.length = 0; },
      };
      try {
        const ws = new WebSocket(wsUrl('/api/events'));
        ws.onopen = () => { if (token) ws.send(JSON.stringify({ type: 'auth', token })); };
        ws.onmessage = (m) => {
          try {
            const d = JSON.parse(m.data);
            if (d.type === 'incoming_call') emit('incoming_call', { reason: d.reason || '' });
          } catch {}
        };
        sub._ws = ws;
      } catch (e) { /* events WS optional; demo hook still works */ }
      // demo / manual trigger
      window.CV = window.CV || {};
      window.CV.simulateIncomingCall = (reason) => emit('incoming_call', { reason });
      return sub;
    },

    /* board() — GET /api/board (token via x-cv-token header). */
    async board() {
      try {
        const r = await fetch('/api/board', {
          headers: token ? { 'x-cv-token': token } : {},
        });
        if (r.ok) return r.json();
      } catch {}
      return sampleBoard();
    },

    /* hangUp() — tear down the real audio engine. */
    async hangUp() {
      try { rt.stop(); } catch {}
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
      if (rt.active) {
        // Drive bars from the real mic level (plus a little life).
        const base = rt.level;
        wfAmps = wfAmps.map(() => Math.max(0.05, Math.min(1, base * (0.6 + Math.random() * 0.9))));
      } else {
        wfAmps = wfAmps.map((_, i) => {
          const target = Math.random() * 0.85 + 0.05;
          return wfAmps[i] + (target - wfAmps[i]) * 0.35;
        });
      }
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
    rt.muted = muted;
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
