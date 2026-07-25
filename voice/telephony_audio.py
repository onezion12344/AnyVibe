"""voice/telephony_audio.py — μ-law 8kHz ↔ PCM16 24kHz conversion for telephony.

Twilio Media Streams deliver/accept 8kHz μ-law (G.711) audio, while the StepFun
Realtime API speaks PCM16 mono 24kHz. This module bridges the two, handling both
companding (μ-law ↔ linear PCM16) and resampling (8k ↔ 24k).

Two code paths:
  * Native ``audioop`` (CPython ≤ 3.12) — fast C implementation of ulaw2lin,
    lin2ulaw, and ratecv. This is the preferred path.
  * Pure-numpy fallback — for Python ≥ 3.13, where ``audioop`` was removed from
    the stdlib (PEP 594). If you are on 3.13+ you can either ``pip install
    audioop-lts`` (a drop-in backport that restores ``import audioop``) or rely
    on the numpy fallback implemented here.

The rate-conversion state (returned as the 2nd tuple element) must be threaded
through successive calls in a single direction to keep the resampler filter
continuous; pass ``None`` on the first call.
"""

try:
    import audioop
    _HAVE_AUDIOOP = True
except ImportError:
    _HAVE_AUDIOOP = False
    import numpy as np

WIDTH = 2
CHANNELS = 1

if _HAVE_AUDIOOP:
    def ulaw8k_to_pcm24k(ulaw_bytes: bytes, state):
        pcm8k = audioop.ulaw2lin(ulaw_bytes, WIDTH)
        pcm24k, state = audioop.ratecv(pcm8k, WIDTH, CHANNELS, 8000, 24000, state)
        return pcm24k, state

    def pcm24k_to_ulaw8k(pcm24k_bytes: bytes, state):
        pcm8k, state = audioop.ratecv(pcm24k_bytes, WIDTH, CHANNELS, 24000, 8000, state)
        ulaw = audioop.lin2ulaw(pcm8k, WIDTH)
        return ulaw, state
else:
    _BIAS, _CLIP = 0x84, 32635
    def _lin2ulaw(pcm):
        sign = (pcm < 0).astype(np.int32) * 0x80
        mag = np.minimum(np.abs(pcm.astype(np.int32)), _CLIP) + _BIAS
        exp = np.floor(np.log2(mag)).astype(np.int32) - 7
        exp = np.clip(exp, 0, 7)
        mant = (mag >> (exp + 3)) & 0x0F
        return (~(sign | (exp << 4) | mant) & 0xFF).astype(np.uint8).tobytes()
    _u2l = None
    def _ulaw2lin(u):
        global _u2l
        if _u2l is None:
            x = np.arange(256, dtype=np.int32); ux = ~x & 0xFF
            sign = ux & 0x80; exp = (ux >> 4) & 0x07; mant = ux & 0x0F
            mag = ((mant << 3) + _BIAS) << exp
            _u2l = np.where(sign != 0, _BIAS - mag, mag - _BIAS).astype(np.int16)
        return _u2l[np.frombuffer(u, dtype=np.uint8)]
    def _resample(pcm, src, dst):
        if len(pcm) == 0: return pcm
        n = int(round(len(pcm) * dst / src))
        xi = np.linspace(0, len(pcm) - 1, n)
        return np.interp(xi, np.arange(len(pcm)), pcm).astype(np.int16)
    def ulaw8k_to_pcm24k(ulaw_bytes, state):
        return _resample(_ulaw2lin(ulaw_bytes), 8000, 24000).tobytes(), state
    def pcm24k_to_ulaw8k(pcm24k_bytes, state):
        pcm = np.frombuffer(pcm24k_bytes, dtype=np.int16)
        return _lin2ulaw(_resample(pcm, 24000, 8000)), state
