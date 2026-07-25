/* voice-control.js — small, reusable StepFun /api/call browser client.
 * The company dashboard owns the surrounding UI; this module only owns
 * microphone capture, PCM playback, and call lifecycle.
 */
(() => {
  const RATE = 24000;
  const CHUNK = 960; // 20 ms of PCM16 at 24 kHz

  class VoiceControl {
    constructor({ token = '', onStatus, onTranscript, onLog, onDispatched, onAgentState } = {}) {
      this.token = token;
      this.onStatus = onStatus || (() => {});
      this.onTranscript = onTranscript || (() => {});
      this.onLog = onLog || (() => {});
      this.onDispatched = onDispatched || (() => {});
      this.onAgentState = onAgentState || (() => {});
      this.ws = null;
      this.ctx = null;
      this.stream = null;
      this.source = null;
      this.node = null;
      this.sink = null;
      this.playHead = 0;
      this.sources = new Set();
      this.active = false;
      this.muted = false;
      this.level = 0;
      this.refreshingSession = false;
    }

    _wsUrl() {
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
      return `${scheme}://${location.host}/api/call`;
    }

    async connect() {
      if (this.active) return;
      this.onStatus('connecting', 'Connecting to Yellow Sheep…');
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        this.ctx = new AC({ sampleRate: RATE });
        await this.ctx.resume();
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
        });
        this.ws = new WebSocket(this._wsUrl());
        this.ws.binaryType = 'arraybuffer';
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error('voice connection timed out')), 8000);
          this.ws.onopen = () => { clearTimeout(timer); resolve(); };
          this.ws.onerror = () => { clearTimeout(timer); reject(new Error('voice WebSocket error')); };
        });
        this.ws.onmessage = (event) => this._onMessage(event);
        this.ws.onclose = (event) => {
          const wasActive = this.active;
          this.stop();
          if (event.code === 4401 && !this.refreshingSession) {
            // A page held open while the local dev server reloads can have an
            // old capability.  Reload once to obtain a newly minted short-lived
            // capability instead of leaving the Call button in a silent loop.
            this.refreshingSession = true;
            this.onStatus('connecting', 'Refreshing secure voice session…');
            window.setTimeout(() => window.location.reload(), 250);
            return;
          }
          if (wasActive) {
            const detail = event.code && event.code !== 1000
              ? ` (${event.code}${event.reason ? `: ${event.reason}` : ''})`
              : '';
            this.onStatus('error', `Voice connection closed${detail}`);
            this.onLog(`Voice connection closed${detail}`);
          }
        };
        if (this.token) this.ws.send(JSON.stringify({ type: 'auth', token: this.token }));

        this._startCapture();
        this.playHead = this.ctx.currentTime + 0.12;
        this.active = true;
        this.onStatus('connected', 'Live — speak naturally');
        this.onLog('Voice channel connected');
      } catch (error) {
        this.onStatus('error', error?.message || 'Unable to start voice');
        this.onLog(`Voice error: ${error?.message || error}`);
        this.stop();
        throw error;
      }
    }

    _startCapture() {
      this.source = this.ctx.createMediaStreamSource(this.stream);
      this.node = this.ctx.createScriptProcessor(4096, 1, 1);
      this.sink = this.ctx.createGain();
      this.sink.gain.value = 0;
      this.source.connect(this.node);
      this.node.connect(this.sink);
      this.sink.connect(this.ctx.destination);
      const inRate = this.ctx.sampleRate || RATE;
      this.node.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
        this.level = Math.min(1, Math.sqrt(sum / input.length) * 4);
        if (this.muted || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        let samples = input;
        if (inRate !== RATE) {
          const ratio = RATE / inRate;
          const out = new Float32Array(Math.round(input.length * ratio));
          for (let i = 0; i < out.length; i++) {
            const src = i / ratio;
            const i0 = Math.floor(src);
            const i1 = Math.min(i0 + 1, input.length - 1);
            const frac = src - i0;
            out[i] = input[i0] * (1 - frac) + input[i1] * frac;
          }
          samples = out;
        }
        const pcm = new Int16Array(samples.length);
        for (let i = 0; i < samples.length; i++) {
          const s = Math.max(-1, Math.min(1, samples[i]));
          pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        try { this.ws.send(pcm); } catch {}
      };
    }

    _onMessage(event) {
      if (typeof event.data === 'string') {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'dispatched') {
            this.onDispatched(data);
            this.onTranscript(`工程师已接单：${data.task || '任务已派发'}`);
          } else if (data.type === 'assistant-text') {
            const text = String(data.text || '').trim();
            if (text) this.onTranscript(`Yellow Sheep: ${text}`);
          } else if (data.type === 'assistant-state') {
            this.onAgentState(data);
            if (data.state === 'dispatching') {
              this.onStatus('connected', data.text || 'Connecting the CEO team…');
              this.onLog('Yellow Sheep is handing the request to the CEO team…');
            } else if (data.state === 'listening') {
              this.onStatus('connected', 'Live — speak naturally');
            }
          } else if (data.type === 'end-call') {
            const delay = Math.max(0, Number(data.delay_ms) || 0);
            this.onAgentState({ state: 'ending', ...data });
            this.onStatus('connected', 'Yellow Sheep is saying goodbye…');
            this.onLog('Yellow Sheep is ending the call at your request');
            window.setTimeout(() => {
              if (!this.active) return;
              this.stop();
              this.onStatus('idle', 'Ready — tap Call to start the voice conversation');
              this.onLog('Call ended by Yellow Sheep');
            }, delay);
          } else if (data.type === 'transcript') {
            const transcript = String(data.text || '').trim();
            if (transcript) {
              this.onTranscript(`You said: ${transcript}`);
              this.onLog(`Heard: ${transcript}`);
            }
          } else if (data.type === 'barge-in') {
            this._flushPlayback();
            this.onLog('Speech detected');
          } else if (data.type === 'call-state' && data.state === 'speech-stopped') {
            this.onLog('Processing your request…');
          } else if (data.type === 'response-done') {
            this.onLog('Yellow Sheep finished speaking');
          }
        } catch {}
        return;
      }
      this._playPCM(new Int16Array(event.data));
    }

    _playPCM(pcm) {
      if (!this.ctx || !pcm.length) return;
      const buffer = this.ctx.createBuffer(1, pcm.length, RATE);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;
      const source = this.ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(this.ctx.destination);
      const now = this.ctx.currentTime;
      if (this.playHead < now + 0.02) this.playHead = now + 0.12;
      source.start(this.playHead);
      this.playHead += buffer.duration;
      this.sources.add(source);
      source.onended = () => this.sources.delete(source);
    }

    _flushPlayback() {
      this.sources.forEach((source) => { try { source.stop(); } catch {} });
      this.sources.clear();
      if (this.ctx) this.playHead = this.ctx.currentTime + 0.12;
    }

    toggleMute() {
      this.muted = !this.muted;
      if (this.stream) this.stream.getAudioTracks().forEach((track) => { track.enabled = !this.muted; });
      this.onStatus(this.muted ? 'muted' : 'connected', this.muted ? 'Muted — tap Unmute to speak' : 'Live — speak naturally');
      this.onLog(this.muted ? 'Microphone muted' : 'Microphone unmuted');
      return this.muted;
    }

    stop() {
      this.active = false;
      try { this.node && (this.node.onaudioprocess = null); } catch {}
      try { this.source?.disconnect(); } catch {}
      try { this.node?.disconnect(); } catch {}
      try { this.sink?.disconnect(); } catch {}
      try { this.stream?.getTracks().forEach((track) => track.stop()); } catch {}
      this._flushPlayback();
      try { if (this.ws && this.ws.readyState < 2) this.ws.close(1000, 'user hangup'); } catch {}
      try { this.ctx?.close(); } catch {}
      this.ws = null; this.ctx = null; this.stream = null;
      this.source = null; this.node = null; this.sink = null;
      this.muted = false; this.level = 0;
    }

    hangUp() {
      this.stop();
      this.onStatus('idle', 'Ready — tap Call to start the voice conversation');
      this.onLog('Call ended');
    }
  }

  window.VoiceControl = VoiceControl;
})();
