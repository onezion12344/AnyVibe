/**
 * audio-worklet.js — AudioWorkletProcessor for mic capture
 *
 * Runs off the main thread.  Captures Float32 frames from the mic,
 * downsamples to 24 kHz (linear interpolation if the context sample-rate
 * differs), converts to Int16 PCM, and posts the result to the main thread.
 *
 * Published under the name "cv-mic-processor" so the main thread loads it
 * via audioContext.audioWorklet.addModule('/static/audio-worklet.js').
 */

class CvMicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    /** Target rate we send to the server */
    this.targetRate = 24000;
    /** Will be set by the main thread via postMessage before first process() */
    this.contextRate = this.targetRate;
    this._ready = false;
  }

  /**
   * Main thread calls this once after addModule resolves:
   *   port.postMessage({ type: 'init', contextRate: ctx.sampleRate });
   */
  static get parameterDescriptors() {
    return [];
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const channelData = input[0]; // Float32Array

    // Downsample to 24 kHz if context rate differs (linear interpolation)
    let samples = channelData;
    if (this.contextRate !== this.targetRate) {
      const ratio = this.targetRate / this.contextRate;
      const outLen = Math.round(channelData.length * ratio);
      const out = new Float32Array(outLen);
      for (let i = 0; i < outLen; i++) {
        const src = i / ratio;
        const i0 = Math.floor(src);
        const i1 = Math.min(i0 + 1, channelData.length - 1);
        const frac = src - i0;
        out[i] = channelData[i0] * (1 - frac) + channelData[i1] * frac;
      }
      samples = out;
    }

    // Float32 → Int16 PCM
    const len = samples.length;
    const pcm = new Int16Array(len);
    for (let i = 0; i < len; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }

    // Post Int16 PCM to the main thread for WebSocket transmission.
    // Copy the buffer (transfer ownership) to avoid extra copies.
    this.port.postMessage(pcm, [pcm.buffer]);
    return true; // keep processor alive
  }
}

registerProcessor('cv-mic-processor', CvMicProcessor);
