# UI & Company-View Design Notes (recorded, not yet built)

Captured 2026-07-24/25 from owner direction. Build AFTER call + tool-call are solid.

## 1. Company View — the headline UI idea
Visualize the whole chain live, like a real org:

```
You  ──call──▶  🐑 Yellow Sheep (CS receptionist)
                     │  (log shows the ACTUAL tool call, not a summary)
                     ▼
                   CEO  ──dispatch──▶  the company/org
                                        ├─ CTO → engineers
                                        ├─ CMO → content
                                        └─ COO → ops   (à la OpenOPC "How OpenOPC Works" org chart)
```
- Owner ask: "我打电话给黄羊，然后黄羊打给CEO（log反映实际的 tool call），CEO dispatch 给公司."
- **Visibility gap (owner: "它做了什么操作，我能看到吗")**: today the board shows only the task + final summary. We need to surface the **actual tool calls / actions** the CEO + org members take — a live activity/tool-call log per node.
- Reference layout: the OpenOPC org chart (CEO → CTO/CMO/COO → specialists), nodes light up / stream their current action as work flows down.

## 2. Kanban — replicate, don't embed (更拟人、可爱)
- Owner wants a board that copies the strengths of good agent boards (Vibe Kanban: PLAN→PROMPT→REVIEW, parallel agents, auto status transitions, per-agent lanes, review/diff surface) — see the earlier 对标 notes — but styled **cuter / more anthropomorphic** (Yellow-Sheep brand).
- **Qoder as an OpenOPC backend: NOT supported** (OpenOPC registry = claude_code/cursor/codex/opencode; no qoder). Adding a `QoderAdapter(ExternalAgentAdapter)` in `opc/layer3_agent/adapters/` is feasible later (Qoder has a headless CLI). For now: **just replicate Qoder's kanban look**, cuter.

## 3. Avatar — the talking Yellow Sheep 🐑 (tiered)
- **Tier 1 (do first, no rigging):** expression PNG swap keyed to call-state (idle→smile-calm, listening→attentive, dispatching→thinking, done→happy-thumbs-up) + audio-amplitude bounce/glow (WebAudio AnalyserNode on the playback stream) + CSS idle breathing/scarf-sway. Uses existing assets, plugs into the call page.
- **Tier 2 (real lip-sync):** Live2D (pixi-live2d-display + PixiJS, AnalyserNode RMS → mouth param; CDN, no build) — needs the sheep **rigged** into a Cubism model. Rive is the alt.
- **Tier 3 (photoreal plugins Tavus/Simli/Hedra):** human-only → NOT for a stylized sheep. Skip.
- Assets: `~/Projects/onezion-the-yellow-sheep/processed-assets/02-character-expressions/` (smile-calm, thinking, happy-thumbs-up, surprised, serious-focused) + `cycleExpression` pattern.

## 4. Aesthetics
Yellow-Sheep deep-space nautical: `--bg #0d1b2a`, coral `#e07a5f` / gold `#d4a843` / teal `#3a8a8a`, Space Grotesk + Noto Sans SC, glow + pulsar rings. Slogan 「为创造，再一次信仰之跃」.

## Priority (owner)
1. **Call + tool-call solid** (in progress — evaluating turnkey voice frameworks vs current StepFun bridge).
2. Company view + tool-call visibility.
3. Cuter kanban (replicate Qoder strengths).
4. Talking sheep avatar (Tier 1 → Tier 2).

## 5. Layered / async progressive-response design (owner idea)
Never leave the user in silence while a slow tier works — tiered feedback:
- **T0 (instant):** fast brain speaks a filler ("好的，我查一下，稍等哈") + optional clarifying question.
- **T1 (seconds):** step-3.7-flash gives a preliminary answer from its own knowledge / quick lookup.
- **T2 (minutes):** CEO returns the strong verdict → spoken as a follow-up in the SAME call, or ring-back if the call ended.
Each tier answers with what it has now, upgrades when the higher tier reports → saves user time.

**Pipecat implementation (confirmed feasible):**
- filler-while-tool-runs: push a `TTSSpeakFrame` when `dispatch_to_engineer` is invoked.
- `dispatch_to_engineer` returns FAST (ack), doesn't block the turn; fast LLM can give a first-pass answer.
- CEO runs as a background task; on completion, INJECT an out-of-band assistant turn into the live Pipecat pipeline (`queue_frame` → TTS → spoken) — proactive mid-call update, no polling.
- fallback: call ended → agent-calls-you ring-back (already built).
This is a strong reason to build on Pipecat (hand-rolled bridge can't cleanly inject async turns). AEC (hands-free) also comes free with Pipecat's WebRTC transport.

## 6. Digital Pet (Codex-pet ecosystem) — RESEARCHED, recorded, not building yet
**Verdict: mature, 接入即用 — adopt the Codex-pet format + web SDK. The owner's "比特化"(sprite) instinct is right — the format IS a sprite-sheet.**

- **Codex Pet** (merged into Codex CLI May 2026): animated companion, states = idle / running / waving / jumping / working / waiting / review / failed (+ 16 look angles v2). Format (reverse-engineered, community-standard, no official spec): `pet.json` (manifest: animation grid rows, spriteVersion) + `spritesheet.webp` (atlas, e.g. v1 1536×1872 8×9 grid).
- **`codex-pet-companion`** (JS/Web Component) = the **directly usable** piece for us: `<codex-pet>` tag + `pet.play('waving',{returnTo:'idle'})` / `SpriteAnimator.setState('working')` → exactly the **tool-call → preset-motion** mapping we want, web-embeddable → drops onto the call page.
- **`codex-pet-gen`** auto-generates custom Codex-compatible pet packages via image-gen → we generate a **Yellow-Sheep sprite-sheet** in Codex-pet format.
- Ecosystem (desktop, FYI): CoPet, OpenPet(+MCP/HTTP/CLI), OpenPets(macOS+MCP), UniPet, Peon-Pet — map real agent events (prompt/tool-call/waiting/success/error) → pet reactions. We want the **web SDK**, not the desktop apps.
- **Recommended integration (later):** generate a Yellow-Sheep pet package (Codex format, ~8 motions: idle/listening/thinking/working/celebrate/failed) → embed `codex-pet-companion` on the call page → map our call+agent states to `pet.play(...)`. Low effort, mature. This is the pet form; supersedes the static-PNG Tier-1 avatar note (§3).
- Full report: `docs/research/digital-pet.md`.
