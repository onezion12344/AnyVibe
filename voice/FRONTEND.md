# voice/FRONTEND.md — Official Pipecat Frontend for Coding Vibe Voice Bot

## Decision

Adopted the **official Pipecat JavaScript SDK** (`@pipecat-ai/client-js`) + the **official SmallWebRTC transport** (`@pipecat-ai/small-webrtc-transport`) as the browser frontend for the StepFun-powered voice bot.

Why not `@pipecat-ai/voice-ui-kit`:
- `voice-ui-kit` is a full React 19 + Vite + Tailwind 4 component library — it requires a Node.js build step (Vite, React compiler, TSX), a `package.json` with peer deps (React 18+, `client-react`, `daily-transport`, etc.), and a full React app scaffold. It ships templates but imposes significant complexity for a one-file frontend.
- The server already has `SmallWebRTCTransport` — the light client (`client-js` + `small-webrtc-transport`) connects to it with zero React overhead.

**Chosen stack (minimum dev):**
```
voice/frontend/
├── index.html          ← vanilla JS + ESM imports from /node_modules/
├── package.json        ← npm manifest
├── node_modules/       ← NOT committed (in .gitignore)
└── .gitignore
```

---

## Packages (installed 2026-07-25)

| Package | Version | Role |
|---|---|---|
| `@pipecat-ai/client-js` | 1.13.0 | Core JS SDK: PipecatClient, RTVIEvent, callbacks |
| `@pipecat-ai/small-webrtc-transport` | 1.10.6 | Browser WebRTC transport for SmallWebRTCTransport |

Both live in `voice/frontend/node_modules/` and are served by the FastAPI server at `/node_modules/` so ESM imports resolve in-browser without a build step.

---

## How It Works

```
Browser (voice/frontend/index.html)
  ├── SmallWebRTCTransport({ offerUrlTemplate: "/api/offer" })
  │       └── on connect(): creates RTCPeerConnection, posts SDP offer to /api/offer
  ├── PipecatClient({ transport, enableMic: true, enableCam: false })
  └── RTVIEvent callbacks: onBotReady, onConnected, onError, …
         │
         ▼ POST {sdp, type:"offer"}
FastAPI  voice/server.py
  POST /api/offer → SmallWebRTCConnection.initialize() → SDP answer
  └── asyncio.create_task(_run_bot) → voice/bot.py pipeline
         │
         ▼ SmallWebRTCTransport + audio frames
Pipecat  voice/bot.py
  StepFun STT → Silero VAD → StepFun LLM (+ dispatch_to_engineer tool) → StepFun TTS
```

---

## Run Commands

### Terminal 1 — Start the server

```bash
cd /Users/onezion12344/Projects/coding-vibe-pipecat
CV_PIPECAT_HOST=127.0.0.1 /Users/onezion12344/miniforge3/bin/python3 voice/server.py
```

Server starts at `http://127.0.0.1:7860`. It serves:
- `GET /` → `voice/frontend/index.html` (the official Pipecat client)
- `GET /node_modules/...` → `voice/frontend/node_modules/...` (ESM module files)
- `POST /api/offer` → SDP offer/answer exchange

### Terminal 2 — Open in browser

```
http://localhost:7860/
```

Click **Call**, allow the mic, and speak.

### Verification

```bash
# 1. Server boots
curl -s http://localhost:7860/ -o /dev/null -w '%{http_code}'
# → 200

# 2. Frontend HTML is served
curl -s http://localhost:7860/ | head -3
# → <!DOCTYPE html>

# 3. node_modules ESM files are accessible
curl -s -o /dev/null -w '%{http_code}' http://localhost:7860/node_modules/@pipecat-ai/client-js/dist/index.js
# → 200
```

---

## What Was Verified (2026-07-25)

| Check | Result |
|---|---|
| Existing server on `feat/pipecat-voice` boots | ✅ `curl localhost:7860/ → 200` |
| `npm install @pipecat-ai/client-js @pipecat-ai/small-webrtc-transport` | ✅ 24 packages, 0 vulnerabilities |
| Server mounts `/node_modules/` for ESM imports | ✅ server.py updated |
| `server.py` still boots (server unchanged, only adds mounts) | ✅ same HTTP 200 |
| Full end-to-end call (connect → hear bot audio) | ⬜ **NOT TESTED** — requires StepFun key + STT/TTS round-trip |

---

## Honest TODO

- [ ] **E2E call test**: actually click Call in browser and confirm audio round-trip (requires running server with real keys and a browser with mic access).
- [ ] **Auth header forwarding**: the `SmallWebRTCTransport` POSTs to `/api/offer`. If `CV_API_TOKEN` is set, the transport needs to send `x-cv-token`. Currently the server requires it but the JS client has no auth mechanism — either set `CV_API_TOKEN=""` in dev, or add an `offerUrlTemplate` that encodes the token in the URL query string, or switch to the deprecated `connectionUrl` with a query param. For local dev this is fine (no token set).
- [ ] **Build the frontend properly**: for production, serve `index.html` via a Vite dev server or pre-bundle with a bundler. Currently it relies on the FastAPI `/node_modules/` mount which is fine for dev but exposes the entire `node_modules` tree.
- [ ] **Voice UI Kit**: if the project later needs a rich UI (transcript panel, visualizer, controls), `@pipecat-ai/voice-ui-kit` is the right choice — it just requires a React + Vite build. See the `voice-ui-kit` README at `https://github.com/pipecat-ai/voice-ui-kit`.
