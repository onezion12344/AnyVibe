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

## D9: Realtime audio tool-calling is unreliable everywhere → decouple (text LLM decides)
- **Evidence:** empirical 2/10 fire rate on stepaudio-2.5-realtime with tool_choice=auto (worse with stronger prompts); StepFun engineer (Step-Audio #31) confirms "a probability of triggering toolcall"; OpenAI Realtime community reports the identical ~50% problem. Universal realtime-S2S limitation, not tunable.
- **Decision:** the realtime model does VOICE only; a text LLM (step-3.7-flash) reads the transcript and makes the dispatch decision (reliable text tool-calling). This is our live classifier AND Pipecat's cascaded design.
- **Implication:** adopt Pipecat cascaded (STT → text-LLM+tools → TTS), NOT a realtime S2S brain for dispatch.

## D10: Persistent orchestrator session (not spawn-per-task) + preset role team
- **Insight (owner):** the real requirement isn't a specific framework — it's that we DON'T open a new session per task. Keep a **persistent main/CEO agent session** and inject the transcript stream into it (~every 10s or per new sentence). The main agent orchestrates an **agent team of preset roles** (each role = a system prompt); the realtime voice model meanwhile keeps the user company (clarify, soothe, chat from its own knowledge) while the CEO does async work + delegates to its org.
- **This subsumes the separate step-3.7-flash classifier** — a persistent CEO reads the stream and decides itself (the classifier only existed because claude-code is spawn-per-task). Tiered/async feedback (D-notes §5) rides on this.
- **How to realize:**
  - **OpenOPC** — persistent org (boss→team), natural fit. Default fallback.
  - **claude-code** — works too IF we reuse ONE session (`--resume`/same session id) and inject, instead of spawning per task. Main agent + Task subagent team.
  - **Qoder SDK** — desirable (competition track) IF it supports persistent sessions + multi-agent orchestration (research pending → [[qoder-sdk-research]]).
- **Team roles = presets**, user-selectable on the web kanban (pick which team/roles staff the company).
- Requirement in one line: **inject into the same main agent every turn; that agent orchestrates a preset role team.**

## D10a: Qoder SDK CAN realize the persistent-company (D10) — and fits the competition
- **Verdict (research):** Qoder Agent SDK supports all D10 needs: persistent/resumable sessions (`QoderSDKClient` + `resume`/`continue`/`forkSession`), multi-agent orchestration (`AgentDefinition` subagents + `Agent` tool; Cloud Managed Agents coordinator with create_agent/send_to_agent/mailbox), custom per-agent role prompts (`AgentDefinition.prompt`), tools/MCP/streaming. API is Claude-Agent-SDK-shaped.
- **Mapping:** `QoderSDKClient` = persistent main/CEO session (inject transcript each turn); `agents={}` = preset role team (user-selectable on the kanban).
- **Competition:** "Alibaba Cloud × Qoder Hackathon Singapore 2026" (Spec-Driven + Quest Mode) — building on Qoder SDK enters the track. Ref: luma.com/92h6pyl1.
- **Caveats:** SDK delegation is per-task (orchestration logic lives in the main prompt); cross-restart persistence = manage session IDs; Cloud Managed Agents coordinator needs a Qoder account.
- **Fallback:** OpenOPC (zero external dep, local control) if Qoder cloud/account is a blocker or the track doesn't require the SDK. Full report: docs/research/qoder-sdk-persistent-company.md.
