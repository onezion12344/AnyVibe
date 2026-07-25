# HANDOFF — coding-vibe (All Worktrees)

**Generated:** 2026-07-25 (Demo Day -1)
**For:** Codex — take over from here
**Context:** Voice-first AI coding companion for AdventureX 2026, Track #04 Qoder「一个人=一支工程团队」, Demo Day 2026-07-26

---

## Quick Start (What's Running NOW)

```bash
# Voice server (StepFun Realtime WS relay, port 7860)
# PID 14050, running via python3
# Serves: voice/frontend/index.html (mute button, mic indicator, StepFun WS bridge)

# Web server (FastAPI, port 5091)
# Running via python3 -c "from web.server import app..."
# Serves: landing page at /docs/landing.html, kanban at /company, index at /
# Static files: /static/ (includes HANDOFF.md), /docs/ (includes landing.html)
```

**All servers verified 200:** landing, company, voice client, HANDOFF.md, project index.

---

## Worktree Map

| Worktree | Branch | Commit | Purpose | Status |
|----------|--------|--------|---------|--------|
| `coding-vibe-main` | `feat/livekit-voice` | `bc92af0` | LiveKit Agent + StepFun plugins + React frontend | LiveKit server connection failed; frontend npm install incomplete |
| `coding-vibe-fanout` | `feat/ceo-fanout` | `8843893` | CEO fan-out directive: decompose work → parallel subagents | Core logic done; integration with kanban pending |
| `coding-vibe-pipecat` | `feat/pipecat-voiceui` | `c7bf03f` | Pipecat WebRTC pipeline (parallel to StepFun WS) | **Built but never tested.** StepFun WS bridge in same worktree works |
| `coding-vibe-staffing` | `feat/openopc-staffing` | `2cf7561` | OpenOPC pre-flight staffing (auto-confirm sessions) | Working; dependent on OpenOPC install |
| `coding-vibe-webui` | `feat/webui` | `b8c5a39` | Mobile voice+kanban UI + FastAPI REST + Cloudflare Tunnel | Deployed at `anyvibe.onezion.top`; press-to-talk voice + TTS |
| **`coding-vibe-qoder`** | **`feat/qoder-company`** | **`56da336`** | **PRIMARY.** StepFun realtime voice relay, Qoder company kanban, landing page, test-feedback loop | **Active — the demo worktree** |

**Shared across all worktrees:** `receptionist/` (adapter layer), `cv_mcp/` (MCP server), `web/` (FastAPI app), `docs/` (research + decisions).

---

## Architecture (CS → CEO → Role Team → Kanban → Callback)

```
Voice (StepFun Realtime)
    │  JSON events + base64 PCM16 24kHz over WebSocket
    ▼
┌─────────────────────────────────────────────┐
│  CS Receptionist (黄羊 Yellow Sheep)         │
│  Model: step-1o-audio (StepFun realtime)     │
│  Role: Takes call, natural conversation,     │
│        classifies intent, dispatches task    │
│  Server: voice/server.py (:7860 /ws relay)   │
│  Frontend: voice/frontend/index.html          │
│           (Web Audio API, zero npm deps)     │
└──────────────┬──────────────────────────────┘
               │ dispatch_to_engineer (tool call)
               ▼
┌─────────────────────────────────────────────┐
│  Text LLM Brain (Intent Classifier)          │
│  Model: step-3.7-flash (via StepFun API)     │
│  Code: web/engineer_dispatch.py              │
│  Decision D9: text model decides, not audio  │
│  (stepaudio-2.5-realtime tool-calling        │
│   verified 2/10 reliable — too unreliable)   │
└──────────────┬──────────────────────────────┘
               │ classify_and_dispatch()
               ▼
┌─────────────────────────────────────────────┐
│  Receptionist (Harness-Agnostic Dispatcher)   │
│  Code: receptionist/core.py                   │
│  dispatch_async() — fire-and-callback        │
│  Fan-out directive: decompose → parallel     │
│  subagents (feat/ceo-fanout branch)          │
│                                               │
│  Adapters (receptionist/adapters/):           │
│  ├─ mock — in-memory, deterministic           │
│  ├─ claude-code — `claude -p --stream-json`  │
│  └─ openopc — `opc exec --org coding-vibe`   │
└──────────────┬──────────────────────────────┘
               │ spawn + stream_status
               ▼
┌─────────────────────────────────────────────┐
│  CEO + Role Team (Qoder / OpenOPC / Claude)  │
│  CEO decomposes → Architect → Builder →      │
│  Reviewer → Tester                           │
│  QoderAdapter: qoder_company/observer.py     │
│               qoder_company/summarizer.py    │
│               (step-3.7-flash for summaries) │
└──────────────┬──────────────────────────────┘
               │ board_update events
               ▼
┌─────────────────────────────────────────────┐
│  Live Kanban Board                           │
│  web/signaling.py — WS /api/events           │
│  web/static/company.html + company.js        │
│  4 columns: Backlog · Running ·              │
│             Needs-Approval · Done            │
│  Inter-agent comms → LLM-summarized → board  │
└──────────────┬──────────────────────────────┘
               │ task complete
               ▼
┌─────────────────────────────────────────────┐
│  Agent Calls You Back                        │
│  web/signaling.py — POST /api/call/ring      │
│  web/push_server.py — APNs + FCM scaffolds   │
│  This is THE differentiator vs Codex/Cursor  │
└─────────────────────────────────────────────┘
```

---

## What Works (Per Worktree)

### coding-vibe-qoder (PRIMARY — Demo Worktree)

| Component | Status | Details |
|-----------|--------|---------|
| StepFun WS voice relay | ✅ E2E verified | `session.created` confirmed through full chain |
| Voice frontend (index.html) | ✅ Working | Mute button, mic indicator, PCM16 24kHz, yellow-sheep theme |
| Landing page | ✅ Working | `/docs/landing.html` — 1011 lines, all links verified |
| Company kanban | ✅ Layout renders | 4 columns, empty state (needs live Qoder backend) |
| Project index | ✅ Working | All internal links verified |
| Test-feedback loop | ✅ Round 1 complete | 2 personas tested, 4 P0/P1 fixed, 0 remaining P0/P1 |
| HANDOFF.md served | ✅ Working | `/static/HANDOFF.md` — 200 |

### coding-vibe-webui (Deployed)

| Component | Status | Details |
|-----------|--------|---------|
| Mobile voice UI | ✅ Live | Press-to-talk, StepFun ASR → TTS → kanban |
| FastAPI REST API | ✅ Working | `/api/dispatch`, `/api/board`, `/api/voice`, `/api/tts` |
| Cloudflare Tunnel | ✅ Live | `anyvibe.onezion.top` |

### coding-vibe-main (LiveKit)

| Component | Status | Details |
|-----------|--------|---------|
| LiveKit agent worker | ✅ Code complete | `livekit/agent.py` — StepFun plugins configured |
| React frontend | ⚠️ Not built | `livekit/frontend/` cloned but `npm install` incomplete |
| LiveKit server | ❌ Connection failed | Worker starts but can't reach LiveKit server |

### coding-vibe-pipecat (Dual Voice)

| Component | Status | Details |
|-----------|--------|---------|
| StepFun WS bridge | ✅ Working | `web/call_bridge.py` — same as qoder worktree |
| Pipecat pipeline | ❌ Never tested | `voice/bot.py` — SmallWebRTCTransport, all StepFun plugins |
| Pipecat TTS bug | 🐛 Known | `StepFunTTSService` sends model ID as voice name (should be `cixingnansheng`) |

### coding-vibe-fanout + coding-vibe-staffing

| Component | Status | Details |
|-----------|--------|---------|
| Receptionist core | ✅ Working | `dispatch()` + `dispatch_async()` + fan-out directive |
| Adapter registry | ✅ Working | Auto-discovery (dir scan + entry points) |
| ClaudeCodeAdapter | ✅ E2E verified | `hello.txt` test passes |
| OpenOPCAdapter | ✅ Working | With staffing pre-flight preset |
| Tests | ✅ 29 passing | `receptionist/tests/test_dispatch.py` |

---

## What DOESN'T Work (All Worktrees)

### P0 — Blocks core demo flow

*None remaining after test-feedback Round 1 fixes.*

### P1 — Functional but has workaround

| ID | Worktree | Issue | Impact |
|----|----------|-------|--------|
| — | All | Per-subagent kanban cards missing | Board shows 1 CEO task card, not individual role cards |
| — | All | OpenOPC DBs corrupted (`demo/tasks.db` 227MB, `dse-agent/tasks.db` 54MB) | Workaround: use fresh `cvlive` project |
| — | qoder | Qoder company backend not live | Kanban shows empty board — needs QoderAdapter with live Qoder backend |

### P2 — Quality / Nice to have

| ID | Worktree | Issue |
|----|----------|-------|
| L4 | qoder | Landing page missing tablet breakpoint (only `max-width: 400px`) |
| L5 | qoder | "5 Preset AI Roles" ambiguous — only 4 named roles visible |
| K1 | qoder | Kanban "Run Demo" button always disabled |
| I2 | qoder | Project index status dot always offline (401 on `/api/board`) |
| — | All | Services via nohup, not launchd — don't survive Mac reboot |
| — | main | LiveKit server needs to be running for agent to connect |
| — | pipecat | Pipecat pipeline never tested with real audio |
| — | pipecat | StepFunTTSService `voice_id` field bug (see above) |

---

## Servers & How to Start

### Voice Server (coding-vibe-qoder, port 7860)

```bash
cd /Users/onezion12344/Projects/adv-x/coding-vibe/coding-vibe-qoder
set -a; source .env; set +a
/Users/onezion12344/miniforge3/bin/python3 voice/server.py
# Serves: http://127.0.0.1:7860/ (voice client)
# WS endpoint: ws://127.0.0.1:7860/ws (StepFun relay)
```

### Web Server (coding-vibe-qoder, port 5091)

```bash
cd /Users/onezion12344/Projects/adv-x/coding-vibe/coding-vibe-qoder
set -a; source .env; set +a
python3 -c "import sys; sys.path.insert(0, '.'); from web.server import app; import uvicorn; uvicorn.run(app, host='127.0.0.1', port=5091)"
# Serves: http://127.0.0.1:5091/ (project index)
#         http://127.0.0.1:5091/docs/landing.html (landing page)
#         http://127.0.0.1:5091/company (kanban)
#         http://127.0.0.1:5091/static/HANDOFF.md (handoff)
```

### WebUI Server (coding-vibe-webui, port 5091)

```bash
cd /Users/onezion12344/Projects/adv-x/coding-vibe/coding-vibe-webui
./web/run.sh
# Deployed at: anyvibe.onezion.top (Cloudflare Tunnel)
```

---

## Known Bugs & Fixes Applied (Round 1)

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| L1 | P0 | Landing: Company Kanban → GitHub Pages 404 | → `localhost:5091/company` |
| L2 | P0 | Landing: Architecture Docs → 404 | → `localhost:5091/docs/success-narrative-vs-mechanism.html` |
| V1 | P1 | Voice: No Mute button | Added mute toggle + track control + mic indicator |
| I1 | P1 | Index: `/HANDOFF.md` → 404 | Copied to `web/static/`, link → `/static/HANDOFF.md` |
| L3 | P2 | Landing: Lightbox missing ESC | Added keydown Escape handler |
| V2 | P2 | Voice: mic-indicator CSS orphaned | Wired to speech_started/speech_stopped events |

Full report: `docs/feedback-loop/round-1.md`

---

## Key Design Decisions

See `docs/DECISIONS.md` in pipecat/qoder worktrees. Critical ones:

| ID | Decision | Rationale |
|----|----------|-----------|
| D3 | Bidirectional calling is the differentiator | Codex/Cursor are one-way; agent calling back is novel |
| D9 | Text LLM owns tool decisions, not audio model | stepaudio-2.5-realtime function calling tested 2/10 reliable |
| D10 | Persistent orchestrator, not per-task spawn | Inject transcript stream into long-lived CEO session |

---

## Priority TODO (For Codex)

### Demo Day (2026-07-26)

1. **Make kanban live** — wire QoderAdapter to actual Qoder backend so board shows cards
2. **Test voice call with real human** — browser mic → StepFun → audio playback, verify latency/quality
3. **Prepare judge talking points** — comparison table "Full-duplex always-on" claim needs defending
4. **Fix landing page tablet breakpoint** — add `@media (min-width: 768px)`
5. **Start all servers** — ensure both 7860 and 5091 are up before demo

### Post-Demo

1. Merge `feat/ceo-fanout` → subagent decomposition into main branch
2. Decide: Pipecat vs StepFun WS for production voice path
3. Fix OpenOPC corrupted DBs or rebuild
4. Move services from nohup → launchd
5. Implement per-subagent kanban cards
6. Test Pipecat pipeline with real audio (or abandon if StepFun WS is good enough)
7. Build native iOS/Android VoIP apps (scaffolds exist)
8. Push all branches to GitHub

---

## File Map (Key Files Across Worktrees)

```
coding-vibe-qoder/                    ← PRIMARY (this worktree)
├── voice/server.py                   ← StepFun WS relay (StepFun Realtime API bridge)
├── voice/frontend/index.html         ← Voice client (Web Audio API, mute btn, mic indicator)
├── web/server.py                     ← FastAPI app (:5091)
├── web/static/index.html             ← Project index page
├── web/static/company.html           ← Kanban board
├── web/static/company.js             ← Kanban JS (WebSocket events)
├── web/static/HANDOFF.md             ← This file (served at /static/HANDOFF.md)
├── web/engineer_dispatch.py          ← Shared classify+dispatch logic
├── web/signaling.py                  ← WS event bus + callback signaling
├── web/call_bridge.py                ← StepFun realtime WS bridge
├── docs/landing.html                 ← Marketing landing page (1011 lines)
├── docs/feedback-loop/round-1.md     ← Test-feedback loop report
├── qoder_company/observer.py         ← Qoder company observer
├── qoder_company/summarizer.py       ← LLM summarizer (step-3.7-flash)
└── HANDOFF.md                        ← Original HANDOFF

coding-vibe-main/                     ← LiveKit branch
├── livekit/agent.py                  ← LiveKit Agent worker (StepFun plugins)
├── livekit/frontend/                 ← Official React frontend (needs npm install)
├── livekit/RUN.md                    ← LiveKit run notes
├── web/call_bridge.py                ← StepFun WS bridge (same as qoder)
├── web/server.py                     ← FastAPI (same structure)
├── docs/DECISIONS.md                 ← Architecture decisions
├── docs/PITFALLS.md                  ← Known pitfalls
└── docs/RUNBOOK.md                   ← Run/deploy instructions

coding-vibe-pipecat/                  ← Pipecat dual-voice branch
├── voice/bot.py                      ← Pipecat pipeline (SmallWebRTCTransport)
├── voice/server.py                   ← Pipecat FastAPI server (SDP exchange)
├── voice/stepfun_stt.py              ← Custom StepFun STT service
├── voice/stepfun_tts.py              ← Custom StepFun TTS service (HAS BUG)
├── voice/frontend/                   ← Official Pipecat JS client
├── web/call_bridge.py                ← StepFun WS bridge (also works here)
└── docs/ARCHITECTURE.html            ← System architecture doc (new/untracked)

coding-vibe-fanout/                   ← CEO fan-out branch
├── receptionist/core.py              ← Receptionist with DEFAULT_ENGINEER_DIRECTIVE
├── receptionist/adapters/            ← 3 adapters (mock, claude-code, openopc)
├── receptionist/registry.py          ← Adapter auto-discovery
└── receptionist/tests/test_dispatch.py ← 26 tests

coding-vibe-staffing/                 ← OpenOPC staffing branch
├── receptionist/adapters/openopc.py  ← Staffing pre-flight (coding-vibe-preset.py)
└── agent.py                          ← LiveKit CodingVibeAgent + delegate_coding tool

coding-vibe-webui/                    ← Deployed web UI branch
├── web/server.py                     ← FastAPI with voice UploadFile, TTS
├── web/static/index.html             ← Press-to-talk mobile UI
├── web/run.sh                        ← Launch script
└── voice_bridge.py                   ← 4-mode voice bridge
```

---

## Environment & Secrets

| Variable | Where | Purpose |
|----------|-------|---------|
| `STEPFUN_API_KEY` | `.env` (all worktrees) | StepFun Realtime + ASR + TTS + step-3.7-flash |
| `CV_API_TOKEN` | `.env` (qoder) | Long-lived shared secret for WS auth |
| `MATON_API_KEY` | `.zshrc` (from Keychain) | Notion API gateway |
| `DEEPSEEK_API_KEY` | `.env` | CEO model (LiveKit mode) |

**`.env` is in `.gitignore` — never commit it.** The `.env.example` file shows required keys.

---

## Contacts & Links

- **GitHub:** `https://github.com/onezion12344/coding-vibe`
- **Deployed:** `https://onezion12344.github.io/projects/coding-vibe/` (landing page)
- **WebUI:** `https://anyvibe.onezion.top` (Cloudflare Tunnel)
- **Sponsors:** Viaim (科大讯飞 headset SDK), Qoder (multi-agent orchestration), StepFun 阶跃星辰 (voice AI models)
- **Founder:** Harry Huang (@onezion12344)
