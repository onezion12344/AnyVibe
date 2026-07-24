# Decisions — coding-vibe (ADR-style)

Context → options → decision → rationale. Includes rejected options.

## D1: Backend-agnostic receptionist + pluggable adapter proxy layer
- **Context:** the CS "receptionist" should be swappable; multiple code-exec harnesses exist.
- **Decision:** `Receptionist` only ever calls the `HarnessAdapter` ABC (spawn/stream_status/result/cancel). Concrete harnesses are adapters behind a registry with auto-discovery (dir + `~/.coding-vibe/plugins/` drop-in + `coding_vibe.adapters` entry-points). In-process, no HTTP.
- **Rationale:** add a harness = add one adapter; the core never learns a CLI. This is what let openopc/qoder slot in.
- **Adapters:** `mock`, `claude-code` (works), `openopc` (works via fresh project), `qoder` (pending feasibility research).

## D2: CS→CEO comms = subprocess streaming (design A), file-mailbox (B) later
- **Decision:** async dispatch + callback (`dispatch_async(on_status, on_complete)`) over subprocess stream-json now; file-mailbox decoupling as a future adapter. Chosen by owner ("先A后可升B").

## D3: The differentiator — bidirectional calls (agent calls YOU)
- **Context:** Codex only supports user→agent voice.
- **Decision:** inbound calls too — `POST /api/call/ring` + `signaling.ring()` + native `ring_native()`. When the CEO finishes/needs input, it rings the user (web full-screen incoming now; CallKit/Telecom later). Owner: "这是我们和 codex 那个不一样的点."

## D4: Voice = StepFun realtime speech-to-speech, CS judges intent via tool-calling
- **Decision:** `stepaudio-2.5-realtime` over WS (24kHz PCM16, server-VAD, barge-in). The CS decides on its own (StepFun `tool_choice:auto`) when to call `dispatch_to_engineer` — no keyword trigger. Owner: "应该是智能判断的."
- **StepFun quirks:** tool schema is nested `{type:"function",function:{...}}` (NOT OpenAI-realtime flat). `function_call` surfaces via `response.function_call_arguments.done` (call_id + args); reply with `function_call_output` + `response.create`.

## D5: WebSocket auth = first-message token (not URL query)
- **Decision:** token sent as first WS frame `{type:auth,token}`, validated before audio/events. Query still accepted (back-compat). Keeps the secret out of access logs. REST uses `x-cv-token` header.

## D6: Real code-exec backend requires EXPLICIT opt-in + token (fail-closed)
- **Decision:** `CV_CALL_BACKEND` defaults to `mock`; real backends (claude-code/openopc) require an explicit env value AND `CV_API_TOKEN`. Server refuses to boot if a dangerous backend is allowlisted for `/api/dispatch` without a token.
- **Rationale:** a spoken request reaching `claude --dangerously-skip-permissions` is RCE; enabling it must be deliberate, never implicit.

## D7: OpenOPC corrupted DBs — sidestep, don't touch
- **Decision:** point openopc at a fresh project (`cvlive`, clean DB) instead of the corrupted `demo`. Never delete/repair the user's `demo`/`dse-agent` DBs without explicit consent.

## D8: Transport — Cloudflare blocked → Oracle reverse tunnel + LAN + localhost
- **Decision:** Cloudflare edge (7844) is blocked on this network. Reach the phone via Oracle reverse SSH tunnel + nginx TLS (`161.118.214.70:8443`), or same-WiFi LAN (`:5443`), or localhost on the Mac. See RUNBOOK.

## Rejected / not-now
- **Cloudflare named tunnel for the call UI** — edge blocked; abandoned for now.
- **Making it a Claude Code plugin** — owner explicitly said NOT a CC plugin; it's a standalone pluggable proxy layer.
- **Deleting/resetting corrupted OpenOPC DBs** — vetoed pending owner consent.
