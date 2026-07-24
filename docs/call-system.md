# Coding Vibe — Bidirectional Realtime Call System

**The differentiator vs Codex:** Codex only lets you call *it* (you talk, it answers).
We are **bidirectional** — you can dial the agent, *and the agent can call you*: when
the CEO/engineer finishes work or needs a decision, it rings your phone like a real
incoming call. Outbound + inbound. That is the wedge.

Goal: beat Codex on the call experience — lower latency, natural barge-in, and the
agent-initiated callback, wrapped in the Yellow Sheep aesthetic.

---

## Phasing

| Phase | Scope | Native? |
|-------|-------|---------|
| **A — In-app realtime call** (build now) | Full-duplex voice over WebSocket to StepFun `stepaudio-2.5-realtime`; barge-in; **both directions** — outbound (you tap Call) and inbound (server pushes a ring → web shows full-screen incoming-call UI + ringtone). | No — web only |
| **B — Native call** | iOS **CallKit** + Android **Telecom/ConnectionService**; VoIP push (APNs PushKit / FCM high-priority) wakes a native incoming-call screen even when the app is closed. coding-vibe becomes a phone contact. | Yes — native app |

Phase A already demonstrates the agent-calls-you differentiator (web full-screen ring).
Phase B makes it feel like a real phone call at the OS level.

---

## Phase A — components & interfaces (parallel-safe)

Three independent workstreams. Each owns distinct files; interfaces are frozen below
so they can be built concurrently and converge without conflict.

### 1. Voice bridge (server)  — `web/call_bridge.py`
Full-duplex audio relay between the browser and StepFun realtime.

- **Endpoint:** `WS /api/call` (query `?token=` when `CV_API_TOKEN` set — same auth as REST).
- Browser sends mic audio frames (PCM16, mono; sample rate per StepFun research —
  16k or 24k) as binary WS messages. Bridge forwards to StepFun realtime
  (`wss://api.stepfun.com/v1/realtime?model=stepaudio-2.5-realtime`, Bearer key).
- StepFun audio deltas are streamed back to the browser as binary frames for playback.
- **Barge-in:** when StepFun's server-VAD reports the user started speaking, cancel the
  in-flight response and stop playback (protocol details from `stepfun-realtime-research`).
- **Tool hook:** the CS persona exposes one realtime tool → `dispatch_to_engineer(task)`,
  which calls `receptionist.dispatch_async(task, backend=<allowlisted>, ...)`. This is
  how a spoken request becomes a real coding task. Goes through the existing
  `_guard_dispatch` + `_check_auth`.
- Emits call/task status onto the control channel (below) so the UI kanban updates live.

### 2. Call UI (frontend)  — `web/static/call.html` (+ assets)
Yellow-Sheep-styled call screen. States:

- `idle` → big Call button (dial the CS).
- `dialing` → pulsar rings (see aesthetics §4.3), connecting.
- `in-call` → live waveform/level meter, mute, hang-up; **agent kanban panel** beside
  it showing dispatched tasks + subagents (reads `/api/board`).
- `incoming` → **full-screen incoming call** (agent is calling you): ringtone, caller =
  "Coding Vibe CEO", accept / decline. Triggered by a control-channel `incoming_call` event.
- Aesthetic: `--bg #0d1b2a`, coral/gold/teal accents, Space Grotesk, glow, pulsar rings,
  star background. Mobile-first ≤480px.

### 3. Signaling / callback (server)  — `web/signaling.py`
The mechanism that lets the agent call the user.

- **Control channel:** `WS /api/events` (auth as above). Client connects on page load
  and stays open. Server pushes JSON events: `incoming_call`, `call_state`,
  `task_update`, `board_update`.
- **Agent → user ring:** `POST /api/call/ring` `{reason, from}` (auth required) → server
  emits `incoming_call` to the connected client(s). Called by the engineer/CS when it
  wants to reach the user (task done, needs a decision).
- Registry of connected clients keyed by session; fan-out ring to all live clients.

### Integration with the receptionist
- The CS receptionist persona is the voice on the line. Its realtime `instructions`
  make it a fast, friendly dispatcher: understand the ask → confirm → call
  `dispatch_to_engineer` → narrate progress from the board.
- The engineer (CEO) runs behind the token-gated `claude-code`/`openopc` backend, fans
  out subagents (the `feat/ceo-fanout` directive), and — when done or blocked — hits
  `POST /api/call/ring` to call the user back.

---

## Security (already in place)
- `/api/dispatch`, `/api/voice`, and the new `/api/call`, `/api/events`, `/api/call/ring`
  all require the `CV_API_TOKEN` bearer (constant-time) when set.
- Fail-closed: enabling a subprocess backend without a token refuses to boot.
- `repo_path` constrained to `CV_ALLOWED_REPO_ROOTS`.
- Token is embedded in the URL handed to the phone (`?token=…`), so only holders can dial.

## Open items pending research
- Exact StepFun realtime event schema, audio format, barge-in events → `stepfun-realtime-research`.
- Codex's interaction model + "what to copy / beat" checklist → `codex-voice-research`.
- Phase B: CallKit / Android Telecom + VoIP push provider choice.
