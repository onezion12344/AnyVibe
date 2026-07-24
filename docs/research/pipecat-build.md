# Pipecat Voice Backend — Build Report

**Branch:** `feat/pipecat-voice`
**Date:** 2026-07-25
**Pipecat version:** 1.6.0 (pip install from PyPI, `pip3` on this machine = Python 3.13)

---

## Files Created

| File | Purpose |
|---|---|
| `web/engineer_dispatch.py` | Backend-agnostic CEO-dispatch shared module |
| `voice/stepfun_tts.py` | Custom `TTSService` subclass → StepFun `POST /v1/audio/speech` |
| `voice/bot.py` | Pipecat voice pipeline (STT→LLM→TTS + dispatch tool) |
| `voice/server.py` | FastAPI server hosting the bot + SDP offer/answer endpoint |
| `voice/client/__init__.py` | Package marker |
| `voice/client/index.html` | Self-contained browser WebRTC client |

**File modified:** `web/call_bridge.py` — refactored to import from `engineer_dispatch.py` (−186 lines, no copy-paste).

---

## How the Pipeline Is Wired

```
Browser (WebRTC)
      │  audio frames
      ▼
SmallWebRTCTransport  [voice/server.py / SmallWebRTCConnection]
      │  PCM16 24kHz mono
      ▼
DeepgramSTTService   (nova-3, language=zh)
      │  text transcript
      ▼
LLMFullResponseAggregator  (turn boundaries, Pipecat 1.6.0)
      │  aggregated text + LLMContextFrame
      ▼
OpenAILLMService     (api_key=STEPFUN_API_KEY,
                       base_url=https://api.stepfun.com/v1,
                       model=step-3.7-flash,
                       tools=[dispatch_to_engineer])
      │  text reply (LLM-generated) + optional function_call
      ▼
StepFunTTSService    [voice/stepfun_tts.py]
  POST /v1/audio/speech  model=step-tts-2  response_format=wav
  → strips WAV header → yields TTSAudioRawFrame chunks @ 24kHz PCM16
      │  audio frames
      ▼
SmallWebRTCTransport → Browser (speakers)
```

**dispatch_to_engineer as a Pipecat function tool:**
`_dispatch_handler(task)` in `voice/bot.py` calls the shared `dispatch_to_engineer(task)` from `web/engineer_dispatch.py`, which spawns the CEO task via `receptionist.dispatch_async()` and returns `{"status":"dispatched","task_id":...}`.

---

## StepFun TTS Approach

`voice/stepfun_tts.py` — `StepFunTTSService(TTSService)`:

- `__init__`: reads `STEPFUN_API_KEY`, `STEPFUN_BASE_URL` from env; calls `super().__init__(sample_rate=24000)`.
- `run_tts(text, context_id)` — **async generator** (Pipecat 1.6.0 contract):
  1. `POST /v1/audio/speech` with `model=step-tts-2`, `response_format=wav`
  2. Strips the 44-byte WAV RIFF header (`_extract_pcm()`)
  3. Yields `TTSAudioRawFrame(audio=chunk, sample_rate=24000, num_channels=1)` in ~960-byte (20ms) chunks
- `start()` / `stop()` — no-ops (StepFun TTS is stateless per-request, no persistent connection)

---

## Async / Layered Injection Status

**Filler speech:** Not yet implemented in the Pipecat pipeline. The Pipecat function-tool mechanism is synchronous from the LLM's perspective — when `dispatch_to_engineer` is called, the LLM gets back the ack text and voices it as its normal reply. To inject filler speech ("好的，我查一下，稍等") *before* the LLM finishes, you would push a `TTSSpeakFrame` into the pipeline as soon as the tool is invoked — the exact Pipecat API for this is `pipeline.queue_frame(TTSSpeakFrame("好的，我查一下，稍等"), FrameDirection.UPSTREAM)`, but `queue_frame` is not a public Pipeline method in 1.6.0; the correct pattern is TBD after reading `pipeline.py` source. A TODO comment is placed in `voice/bot.py` at the `_dispatch_handler` site.

**CEO async injection (out-of-band spoken update mid-call):** Same situation — requires injecting a `TextFrame` + `LLMFullResponseStartFrame` + `LLMFullResponseEndFrame` into the pipeline after the CEO result arrives. TODO comment in `voice/bot.py`.

Both TODOs include the exact Pipecat API candidates to investigate.

---

## What Was Verified

| Check | Result |
|---|---|
| `/Users/onezion12344/miniforge3/bin/python3 -m py_compile` on all 4 Python files | OK (all 4) |
| `from web.engineer_dispatch import ...` | OK — TOOLS schema, config, both functions |
| `import web.call_bridge` (after refactor) | OK — imports from `engineer_dispatch`, no local dup |
| `from voice.stepfun_tts import StepFunTTSService` | OK |
| All 16 Pipecat 1.6.0 imports | OK (all listed above) |
| `from voice.bot import build_pipeline, _build_tools_schema` | OK |
| `_build_tools_schema()` → `ToolsSchema(1 tool)` via shared TOOLS | OK |
| `python -c "import pipecat; print(pipecat.__version__)"` | 1.6.0 |
| `uvicorn` installed | 0.51.0 |
| `pip3 install "pipecat-ai[deepgram,openai,silero,webrtc]"` | Installed (deepgram-sdk, cryptography also pulled) |
| `.env` symlink from main repo | `/Users/onezion12344/Projects/coding-vibe/.env` → `coding-vibe-pipecat/.env` |

---

## What Could NOT Be Verified

- **End-to-end pipeline run** — requires a real Deepgram API key (`DEEPGRAM_API_KEY` in `.env` is not filled in). The `.env.example` has the placeholder but the real `.env` key was not copied.
- **`build_pipeline()` object construction** — `SmallWebRTCTransport(connection, params)` requires a live `SmallWebRTCConnection` and a real SDP offer from a browser; unit-testable only via `voice/server.py` with a browser client.
- **Full end-to-end async-injection** — requires a live browser session to confirm the CEO ring-back / in-call spoken update path.

---

## Exact Run Commands

```bash
# 1. Install (done once)
/Users/onezion12344/miniforge3/bin/pip3 install "pipecat-ai[deepgram,openai,silero,webrtc]"

# 2. Ensure .env has real keys
#    cp /Users/onezion12344/Projects/coding-vibe/.env .
#    (fill in DEEPGRAM_API_KEY and STEPFUN_API_KEY)

# 3. Run the voice server (opens http://localhost:7860)
/Users/onezion12344/miniforge3/bin/python3 voice/server.py

# 4. Open http://localhost:7860 in a browser, click "Connect"
#    Or use the Pipecat prebuilt client:
#    https://unpkg.com/@pipecat-ai/small-webrtc@latest/dist/index.html

# 5. Import-check (no .env needed for this):
/Users/onezion12344/miniforge3/bin/python3 -c "
import sys; sys.path.insert(0, '.')
from web.engineer_dispatch import dispatch_to_engineer, classify_and_dispatch, TOOLS
import web.call_bridge
from voice.stepfun_tts import StepFunTTSService
from voice.bot import build_pipeline, _build_tools_schema
ts = _build_tools_schema()
print(f'ToolsSchema: {len(ts.standard_tools)} tool via shared TOOLS — OK')
"
```

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│  coding-vibe-pipecat  (branch: feat/pipecat-voice)                 │
│                                                                     │
│  web/engineer_dispatch.py  ◄── shared dispatch abstraction         │
│       ├── dispatch_to_engineer(task)  → receptionist → CEO         │
│       ├── classify_and_dispatch(transcript, on_dispatched=cb)      │
│       ├── TOOLS (tool schema)                                       │
│       └── config (CV_CALL_BACKEND, CS_BRAIN_MODEL, …)              │
│                                                                     │
│  web/call_bridge.py  ◄── StepFun realtime bridge (WS transport)   │
│       └── imports dispatch_to_engineer + classify_and_dispatch     │
│                                                                     │
│  voice/stepfun_tts.py  ◄── TTSService → StepFun POST /v1/audio     │
│  voice/bot.py          ◄── Pipecat pipeline (STT→LLM→TTS)          │
│  voice/server.py       ◄── FastAPI: /api/offer + / (client HTML)   │
│  voice/client/         ◄── Browser WebRTC client                   │
└─────────────────────────────────────────────────────────────────────┘
```

**Swappable backends:** To A/B against the StepFun bridge, set `CV_CALL_BACKEND=pipecat` and have `dispatch_to_engineer` delegate to the Pipecat bot instead of the StepFun WS transport. The shared `engineer_dispatch.py` module makes this a single-line change in config.
