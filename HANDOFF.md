# HANDOFF — coding-vibe

**Repo:** https://github.com/onezion12344/coding-vibe
**What this is:** a voice-first AI coding companion. You *call* a fast CS "receptionist" (voice); it decides intent and dispatches coding work to a powerful engineer/CEO backend that fans out subagents; when done it *calls you back*. **Bidirectional calling (agent→you) is the wedge vs Codex.**
**Status:** web voice loop works end-to-end (talk → CS → dispatch → board → callback), verified. Two voice backends exist behind one abstraction. Company-brain + avatar + kanban are researched & designed, not yet built. Native (iOS/Android) are scaffolds.

---

## Architecture (as decided — see `docs/DECISIONS.md` D1–D10a)
```
You ──call──▶ 🐑 CS receptionist (VOICE only)
                 │  transcript
                 ▼
             text brain (owns the tool decision — reliable)  ──dispatch_to_engineer──▶ CEO backend ──▶ org/subagents
                 │                                                                          │ done / needs input
                 └──────────────── agent calls YOU back (ring) ◀───────────────────────────┘
```
Two hard-won principles, both evidence-locked:
- **D9 — voice model speaks; a TEXT LLM owns the tool decision.** Realtime audio tool-calling is ~1/3 reliable on *every* platform (StepFun 2/10 measured; StepFun engineer + OpenAI community + Gemini native-audio all confirm; Gemini half-cascade = text-decision = 90-100%). Never put dispatch in the audio path.
- **D10 — persistent orchestrator, not spawn-per-task.** Keep ONE main/CEO session, inject the transcript stream, it orchestrates a preset role team. Realizable on **Qoder SDK** (D10a — fits the Alibaba×Qoder Singapore 2026 hackathon) or **OpenOPC** (fallback).

## Two voice backends behind one shared abstraction
`web/engineer_dispatch.py` = the shared dispatch brain (`dispatch_to_engineer`, `classify_and_dispatch`, `TOOLS`). Both backends call it → swap by config. **Both are now on `master`** (Pipecat merged from `feat/pipecat-voice`):
| Backend | Where | Transport | State |
|---|---|---|---|
| **StepFun WS bridge** | `web/call_bridge.py` (LIVE on :5091/:5443) | raw WebSocket + Web Audio (gapless-playback fixed) | works; needs headphones (no AEC) |
| **Pipecat** | `voice/` (`voice/server.py` :7860) | WebRTC (smooth + hands-free AEC) | built, imports clean, security-hardened; **not yet A/B-tested with a live call** |

Current live pipeline (master): browser WS `/api/call` → StepFun realtime (voice) → `step-3.7-flash` classifier on transcript (dispatch decision) → CEO (`CV_CALL_BACKEND`).

## Code map
| Path | Purpose |
|---|---|
| `web/server.py` | FastAPI app; auth (token, fail-closed), allowlist; `/`, `/call`, `/api/dispatch|board|task|voice|tts`, mounts routers |
| `web/call_bridge.py` | StepFun realtime voice bridge (WS `/api/call`) — imports the shared dispatch brain |
| `web/engineer_dispatch.py` | **shared** dispatch brain (both voice backends use it) — on master |
| `web/signaling.py` | WS `/api/events` + `POST /api/call/ring` (agent→you) |
| `web/push_server.py` | APNs/FCM device push (native ring, scaffold) |
| `web/static/call.{html,js,css}` + `audio-worklet.js` | Yellow-Sheep call UI + AudioWorklet capture / gapless playback |
| `voice/` | Pipecat bot: `bot.py`, `stepfun_tts.py`, `server.py` (:7860), `client/` |
| `receptionist/` | `Receptionist.dispatch_async` + `adapters/` (mock, claude-code, openopc) + registry |
| `ios/`, `android/` | CallKit+PushKit / Telecom+FCM scaffolds |
| `docs/DECISIONS.md`, `docs/PITFALLS.md`, `docs/RUNBOOK.md`, `docs/research/*`, `docs/ui-and-company-view-notes.md` | decisions, earned bugs, runbook, all research, UI/company-view/pet/kanban design |

## What WORKS (verified)
- Full call loop through the bridge: **voice reply + reliable dispatch (3/3) + board task + ring-back.**
- Security: token auth (first-message WS + header REST), fail-closed on code-exec backends, backend allowlist, repo_path roots, CORS creds off.
- OpenOPC backend executes via a fresh project (`cvlive`); claude-code backend executes. `dispatch_async` checkpoints → board.
- Transport: localhost + LAN (`:5443`) + Oracle public (`:8443` reverse tunnel). Cloudflare edge blocked on this network.

## What's NOT done / TODO
- **P0** — A/B the Pipecat backend with a live call (run `voice/server.py`); pick StepFun-bridge vs Pipecat as default. Confirm audio quality after the gapless-playback fix.
- **P1** — Build the **persistent-company** (D10) on Qoder SDK (competition) or OpenOPC: one persistent orchestrator + preset role team, transcript streamed in, tiered/async feedback (filler → preliminary → CEO verdict).
- **P1** — **Company view + tool-call visibility** (see what the CEO actually did; per-subagent cards) — the "它做了什么操作能看到吗" gap.
- **P2** — Cuter kanban (replicate Qoder's board strengths). Talking **Yellow-Sheep pet** via Codex-pet sprite format + `codex-pet-companion` web SDK. English TTS upgrade (MiMo has an OpenAI-compatible API `mimo-v2.5-tts`; needs a `MIMO_API_KEY`). Native iOS/Android build. launchd for servers/tunnel. `dse-agent` OpenOPC DB recovery (owner-gated). Add a `QoderAdapter` to OpenOPC (registry has no qoder).

## How to run
See `docs/RUNBOOK.md`. Quick local call (master): `http://localhost:5091/call?token=<CV_API_TOKEN>` (headphones). Pipecat: `miniforge3/bin/python3 voice/server.py` → `http://localhost:7860`.

## Branches
`master` (integrated + live bridge + **Pipecat** + shared abstraction) · `feat/pipecat-voice` (merged) · `feat/ceo-fanout` · `feat/openopc-staffing` · `feat/webui`.

## Contact
Owner: Harry (onezion12344).
