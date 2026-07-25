# AdventureX Demo Day — Judge Talking Points

## One-sentence pitch

Coding Vibe turns a voice request into a visible AI engineering company: Yellow
Sheep receives the call, a text brain triages it, a CEO delegates to role agents,
and the user can watch the work and receive the completion callback.

## What is genuinely different

| Capability | Coding Vibe | Typical coding copilot |
|---|---|---|
| Input | Natural voice conversation | Editor/chat prompt |
| Coordination | CS → CEO → role team with internal messages | One assistant session |
| Visibility | Company Kanban + agent communication network | Tool/output pane |
| Feedback | Agent can call the user back when the task completes | User polls or returns to the editor |
| Interaction | Full-duplex during an active call: the user can speak over playback and barge-in flushes the response | Mostly turn-based |

### Be precise about “always-on”

Say: **“The call is full-duplex and continuously listening while the user has
an active voice session.”** Do not imply that a microphone is captured after
the user hangs up. The browser has an explicit Call / Mute / Hang up lifecycle.

## Demo sequence (about 90 seconds)

1. Open `/company`. Voice Control, the role Kanban, and Agent Network Kanban
   are on one screen.
2. Click **Call**, say: “Build a quick sort function and test the edge cases.”
3. Point out the Yellow Sheep CS handoff, then the CEO → Researcher,
   Full-Stack, and QA edges.
4. Show the same events in both projections: role cards move through Running
   and Done while the network shows summarized internal communication.
5. Upload a headshot or use **Auto-generate** to personalize the user node.
6. Explain that completion triggers a callback path, so the user does not need
   to keep polling the board.

## Architecture answer

The realtime audio model handles natural conversation and transcription. A
separate text model makes the dispatch decision because tool-calling is more
reliable there. The receptionist is harness-agnostic: Qoder is the intended
local company backend, with fixture replay as a deterministic demo fallback
when the local SDK or network is unavailable.

## Honest limitation to disclose if asked

The current machine has `qodercli` installed and authenticated, but the Python
`qoder_agent_sdk` import is unavailable and a direct CLI smoke call reported a
network failure. The live UI therefore uses the recorded Qoder company stream
until the SDK/network is available; the adapter contract and board projection
are the same in either mode.
