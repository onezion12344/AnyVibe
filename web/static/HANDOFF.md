# HANDOFF — coding-vibe

**What this is:** a voice-first AI coding companion. You *call* a fast CS "receptionist" (StepFun realtime voice); it judges intent and dispatches coding work to a powerful engineer/CEO backend that fans out subagents; when done it *calls you back*. Bidirectional calling (agent→you) is the wedge vs Codex.

**Status:** web voice loop works end-to-end (talk → CS → dispatch → board → callback). Native (iOS/Android) are scaffolds. See "What works / doesn't" below.

## Architecture
```
Browser call UI ──WS /api/call──► call_bridge ──► StepFun stepaudio-2.5-realtime (voice, barge-in, tool-calling)
     │  ▲                                  │ dispatch_to_engineer(task) [CS decides via tool_choice=auto]
     │  │ WS /api/events (incoming call)   ▼
     │  └───────── signaling ◄──ring()── Receptionist.dispatch_async ──► HarnessAdapter
     └── GET /api/board (kanban ◄ session.json)                          ├─ mock
                                                                         ├─ claude-code  (works)
                                                                         ├─ openopc      (works, fresh project)
                                                                         └─ qoder        (feasibility TBD)
```

## Code map
| Path | Purpose |
|---|---|
| `web/server.py` | FastAPI app; mounts routers; auth/allowlist/fail-closed; `/`, `/call`, `/api/dispatch|board|task|voice|tts` |
| `web/call_bridge.py` | `WS /api/call` full-duplex bridge to StepFun; CS persona + `dispatch_to_engineer` tool → real backend; rings on complete |
| `web/signaling.py` | `WS /api/events` + `POST /api/call/ring` (agent→user); client registry; `ring()` helper |
| `web/push_server.py` | APNs VoIP + FCM senders + device registry (native ring, scaffold) |
| `web/static/call.{html,js,css}` | Yellow-Sheep call UI: idle/dialing/in-call/incoming/ended; real Web Audio engine + mock fallback |
| `receptionist/core.py` | `Receptionist.dispatch_async`; fan-out directive prepend; checkpoints → state |
| `receptionist/adapters/*` | `base.py` (ABC), `claude_code.py`, `openopc.py`, `mock.py`; `registry.py` auto-discovery |
| `ios/`, `android/` | CallKit+PushKit / Telecom+FCM scaffolds + setup READMEs |
| `docs/` | DECISIONS, PITFALLS, RUNBOOK (read these) |
| `~/Projects/OpenOPC/scripts/coding-vibe-preset.py` | staffs the `coding-vibe` org for a project |

## What WORKS
- Real-time voice call to the CS (browser ↔ StepFun), server-VAD, barge-in — verified handshake + audio path.
- CS intelligently dispatches via tool-calling (verified StepFun emits `function_call`).
- `claude-code` backend executes real tasks; `openopc` backend executes via a fresh project (`cvlive`).
- Agent-calls-you: `/api/call/ring` → full-screen web incoming call + ringtone.
- Security: token auth (first-message WS + header REST), fail-closed on code-exec backends, backend allowlist, repo_path roots, CORS creds off.
- Transport: localhost + LAN(:5443, self-signed) + Oracle public(:8443 via reverse tunnel). Cloudflare blocked.

## What DOESN'T (yet)
- **Live voice not yet user-confirmed on a real call** — audio quality/timing needs a real test pass.
- **Kanban shows one CEO task card, not per-subagent cards** — adapter streams CEO text, doesn't emit per-`Task` spawn events.
- **Native iOS/Android** — scaffolds only; need Xcode/Gradle build + APNs/FCM creds + device.
- **Qoder backend** — feasibility research pending (may be GUI-only, no headless path).
- **OpenOPC `demo`/`dse-agent` tasks.db corrupted** — sidestepped via fresh project; `dse-agent` recovery awaits owner OK.
- **Services via nohup, not launchd** — don't survive reboot yet.

## How to run
See `docs/RUNBOOK.md`. Quick local test: open `http://localhost:5091/call?token=<CV_API_TOKEN>` on the Mac.

## TODO (priority)
- **P0** — real-call audio verification; confirm CS→dispatch→board→callback on a live call.
- **P1** — per-subagent kanban cards (emit adapter `Task` tool_use events → session.json); switch/confirm the chosen default backend (claude-code vs openopc); launchd for the servers + tunnel.
- **P2** — Qoder adapter (if feasible); native Phase B (CallKit/Telecom build + push provider); `dse-agent` DB recovery (owner-gated); persist device registry.

## Key decisions / pitfalls
`docs/DECISIONS.md` · `docs/PITFALLS.md`

## Contact
Owner: Harry (onezion12344).
