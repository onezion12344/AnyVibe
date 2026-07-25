# Plan — Qoder Persistent Company (OpenOPC思路, Qoder-adapted)

**Branch:** `feat/qoder-company` (worktree `~/Projects/coding-vibe-qoder`, off `feat/pipecat-voice`)
**Date:** 2026-07-25 · Demo Day 2026-07-26
**Track fit:** AdventureX #04 Qoder「一个人=一支工程团队」— multi-agent collaboration made visible (30% of score) + it's genuinely new work built during the event.

## Vision (from owner)
A persistent AI **company** backend (like OpenOPC, adapted for Qoder): preset roles (also importable from a GitHub/marketplace or auto-generated); inter-agent comms are captured, **LLM-summarized**, and shown on a **kanban**; the voice CS (黄羊) talks to the company **boss (CEO)**. Toggle **Company mode** (persistent org — survives tasks, self-evolves, recruits) vs **Task mode** (ephemeral).

## Ground truth (verified 2026-07-25)
- **Qoder Agent SDK is local by default**: `query()` launches bundled `qodercli` on the Mac; `experimental_cloud_agent` is opt-in. We use LOCAL. Auth = `qodercli login` (reuse via `qodercli_auth()`), no cloud env_id.
- `QoderSDKClient` = persistent multi-turn session (`client.query()`, `receive_messages()` = full session stream, `supported_agents()`, `set_model()`, `interrupt()`). = our persistent CEO.
- `options.agents` (Record) = programmatically defined subagents = our preset role team. Built-in `Agent` tool delegates to them.
- Stream items: `AssistantMessage` (TextBlock / tool_use blocks), `ToolResult`, `ResultMessage`, `StreamEvent` (deltas w/ `include_partial_messages`).
- OpenOPC reference (`~/Projects/OpenOPC`): `opc/` layers, `company-profiles/*.md` (incl. `coding-vibe.md`, `advx-hackathon.md`), `market/`, recruiter/reorg/company-mode already modeled. We adapt the *思路*, not the code.

## Global constraints (binding)
1. Implement the existing `receptionist/adapters/base.py` contract EXACTLY — `StatusEvent.kind ∈ {progress,tool,message,error,done}`, `TaskResult(ok, summary, files_changed, raw)`.
2. **Local qodercli only** — never `experimental_cloud_agent`. No cloud env_id/PAT-for-cloud.
3. **Fixture-first**: everything must run + demo WITHOUT `qodercli login`, by replaying a recorded event stream (env `CV_QODER_FIXTURE=<path>`). Live mode when qodercli is present. Degrade gracefully (failed handle, never crash) — mirror `openopc.py`.
4. Reuse, don't rebuild: `web/engineer_dispatch.py` (dispatch brain), `web/signaling.py` (WS `/api/events`), the existing board (`web/static/`). New code lives in `receptionist/adapters/qoder.py` + a `qoder_company/` package.
5. Secrets only in gitignored `.env`. LLM for summaries = StepFun `step-3.7-flash` (already configured).
6. `git worktree` isolation; commit per task; do NOT push.

## Tasks (SDD — one implementer + review each)
- **T1 — `QoderAdapter`** (`receptionist/adapters/qoder.py` + register in `registry.py` + tests). Persistent `QoderSDKClient` (company mode) / one-shot `query` (task mode); `options.agents` = roles; map `receive_messages()` → StatusEvents; **fixture mode** replays recorded stream. Template: `openopc.py`. *Foundational — do first.*
- **T2 — Company layer** (`qoder_company/company.py`): load a company profile (roles) from `company-profiles/*.md`-style or JSON; **Company mode** = a persistent `QoderSDKClient` kept alive across tasks in a registry; **Task mode** = ephemeral session. `recruiter.add_role()`, `reorg()` stub. Modes toggle via API/env.
- **T3 — Comms → summary → board** (`qoder_company/observer.py`): from the stream, detect inter-agent delegations (`Agent` tool_use → child) + agent messages; summarize each with `step-3.7-flash`; push card ops over `web/signaling.py` WS; board columns Backlog·Running·Needs-Approval·Done + org edges (CEO→role). *The #04 "可视化" centerpiece.*
- **T4 — CS↔CEO + mode toggle UI**: `dispatch_to_engineer` routes to the Qoder company CEO session; web toggle Company/Task; render the org/company view.
- **T5 (stretch) — marketplace/auto-gen roles**: import a role definition from a GitHub URL, or auto-generate a role (system prompt) via LLM, into `options.agents`.

## Demo-critical slice (tonight)
**T1 + T3 + a recorded fixture** = a live "company view": call → CS → CEO → role team fans out → inter-agent messages summarized onto the kanban — demoable even without `qodercli login`. T2/T4 harden it; T5 is a wow-stretch.

## Owner decisions (surface, don't block)
- Is `qodercli` installed + logged in on the Mac (Qoder account / free trial)? Gates LIVE mode. Fixture mode ships regardless.
- Company-profile source: reuse OpenOPC `company-profiles/coding-vibe.md` roles, or define a fresh Qoder-native profile? (Auto-resolving: fresh minimal JSON profile now, import OpenOPC's later.)
