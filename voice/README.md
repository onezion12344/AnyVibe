# Pipecat voice backend (`feat/pipecat-voice`)

A **swappable alternative** to the hand-rolled StepFun WS bridge (`web/call_bridge.py`), built on [Pipecat](https://github.com/pipecat-ai/pipecat) 1.6.0. Same dispatch brain, better transport (WebRTC → smooth audio + hands-free AEC, no headphones).

## Why
Per `docs/DECISIONS.md`:
- **D9** — the voice model only *speaks*; a **text LLM owns the tool decision** (realtime audio tool-calling is ~1/3 reliable everywhere). Pipecat's cascaded STT→LLM→TTS matches this exactly.
- The transport (choppy audio, no AEC) was the real weakness of the raw-WS bridge — WebRTC fixes it.

## Architecture
```
Browser (WebRTC, voice/client/index.html)
   → SmallWebRTCTransport            (voice/server.py, POST /api/offer)
   → Deepgram STT (nova-3, zh+en)
   → OpenAI LLM svc → StepFun step-3.7-flash  (+ dispatch_to_engineer function tool)
   → StepFun TTS   (voice/stepfun_tts.py → POST /v1/audio/speech, step-tts-2)
   → back to browser
        │ dispatch_to_engineer(task)
        ▼
   web/engineer_dispatch.py  ── SHARED with the StepFun bridge ──▶ receptionist → CEO backend
```
`web/engineer_dispatch.py` is the shared abstraction: `dispatch_to_engineer`, `classify_and_dispatch`, `TOOLS`. Both this Pipecat backend and `web/call_bridge.py` import it — swap by config.

## Files
| File | Purpose |
|---|---|
| `voice/server.py` | FastAPI :7860 — `POST /api/offer` (SDP) + serves the client; auth + fail-closed |
| `voice/bot.py` | Pipecat pipeline (STT→LLM→TTS + dispatch tool) |
| `voice/stepfun_tts.py` | Custom `TTSService` → StepFun `step-tts-2` (WAV → PCM frames) |
| `voice/client/index.html` | Browser WebRTC client |
| `web/engineer_dispatch.py` | shared dispatch brain (both backends) |

## Run
```bash
# 1. Install (Pipecat needs its own env; built/verified under miniforge3 py3.13)
/Users/onezion12344/miniforge3/bin/pip3 install "pipecat-ai[deepgram,openai,silero,webrtc]"

# 2. Env — copy the repo .env (needs DEEPGRAM_API_KEY, STEPFUN_API_KEY; CV_API_TOKEN to gate auth)
cp /Users/onezion12344/Projects/coding-vibe/.env .

# 3. Run → http://localhost:7860 → Connect → talk
CV_API_TOKEN=<token> /Users/onezion12344/miniforge3/bin/python3 voice/server.py
```

## Config (env)
| Var | Default | Notes |
|---|---|---|
| `CV_API_TOKEN` | (unset) | gates `/api/offer` (x-cv-token header / `?token=` / body); **required** if `CV_CALL_BACKEND` is a subprocess backend (fail-closed) |
| `CV_PIPECAT_HOST` | `127.0.0.1` | binding `0.0.0.0` is an explicit opt-in |
| `CV_PIPECAT_PORT` | `7860` | |
| `CV_CALL_BACKEND` | `mock` | `claude-code`/`openopc` require a token |
| `CV_CS_BRAIN_MODEL` | `step-3.7-flash` | the text tool-decision LLM |

## Security (applied)
- `/api/offer` token-gated (constant-time); server **fails to start** if a subprocess backend is armed without `CV_API_TOKEN`.
- Binds `127.0.0.1` by default; `session_id` always server-generated; connection cap (`CV_PIPECAT_MAX_CONN`, 32).
- Client log uses `textContent` (no XSS).

## Status / TODO
- ✅ Built, imports clean, security-hardened. **Not yet A/B-tested with a live call.**
- TODO: live A/B vs the StepFun bridge (pick default); English-voice TTS upgrade (MiMo `mimo-v2.5-tts`, needs `MIMO_API_KEY`); layered/async response (filler → preliminary → CEO verdict injected mid-call, `docs/ui-and-company-view-notes.md` §5); then merge to master (folds `engineer_dispatch.py` in).
