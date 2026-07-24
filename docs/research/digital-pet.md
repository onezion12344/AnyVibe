# LLM-Driven Digital Pet / Mascot Framework Research

> Research date: 2026-07-23 | Scope: frameworks an LLM/agent can drive via tool calls to trigger preset motions — for use as a web-embeddable brand mascot

---

## 1. Codex Pet — What It Is, Open Protocol, and Libraries

### What is it

OpenAI's Codex CLI has a **Codex Pet** — an animated terminal/desktop companion that changes animations based on the coding agent's real-time state (idle, running, thinking, waving, failed, review). It was merged into the official Codex TUI in **May 2026** (PR #21206, `fcoury-oai`).

**Pet states / animations:**

| State | What happens |
|---|---|
| `idle` | Breathes, blinks, waits |
| `running-right` / `running-left` | Runs to the left/right |
| `waving` | Greets with a wave |
| `jumping` | Jumps with excitement |
| `working` | Typing / working |
| `waiting` | Waiting for approval |
| `review` | Inspecting with magnifying glass |
| `failed` | Reacts to a task failure |
| `running` | Works on a tiny laptop |
| Look directions (v2) | 16 clockwise look angles |

### Open protocol / spec

**There is no published open spec** for the Codex pet protocol. The community has **reverse-engineered** it. The pet package format (community convention) is:

```
my-pet/
├── pet.json          # manifest: name, animation grid rows, spriteVersionNumber
└── spritesheet.webp  # single atlas image
```

- **v1 atlas**: `1536 × 1872` px, `8 × 9` grid, `192 × 208` px cells
- **v2 atlas**: `1536 × 2288` px, `8 × 11` grid (rows 0–8 = animations, rows 9–10 = 16 look directions)
- `pet.json` declares `spriteVersionNumber: 1` or `2`, which animation row maps to which state name

Official source: [openai/codex codex-rs docs/protocol_v1.md](https://github.com/openai/codex/blob/main/codex-rs/docs/protocol_v1.md) — protocol covers SQ/EQ message queues for Codex session management but **not** the pet file format spec.

The sprite CDN: `https://persistent.oaistatic.com/codex/pets/v1/...`

### Reverse-engineered / third-party libraries

| Library / Tool | Stars | What it does |
|---|---|---|
| **`codex-pet-companion`** (wildcard) | active | Web Component / JS SDK to embed any Codex pet on a website. One `<codex-pet>` tag or `createCodexPetCompanion()`. Supports `play('waving')`, `zoomies()`, `sleep()`, `wake()`, `tuck()`, `recall()`. Also ships `SpriteAnimator` for raw sprite control. |
| **`codex-pet-gen` + `codex-pet-sound`** (CoPet skills) | — | Auto-generates custom Codex-compatible pet packages using Codex's `image_gen` tool + AI sound generation |
| **CoPet** (ChanceYu) | 18 stars | Desktop Tauri app: listens to Codex, Claude Code, OpenCode, Cursor, Copilot CLI, Gemini — maps real agent events (prompts, tool calls, waiting, completion, errors) to pet reactions. Has built-in pets; imports Codex-compatible pet packages |
| **OpenPet** (X-T-E-R) | 49 stars | Local desktop pet runtime + CLI + MCP + HTTP API. Imports Codex-compatible `pet.json + spritesheet.webp` packages. Has `openpet-cli` and `openpet-mcp` skills for agent control |
| **OpenPets** (alterhq) | 79 stars | Native macOS desktop pet + MCP server + CLI. Plugins for Claude Code (quota clouds), Codex usage, etc. Has OpenPetsKit Swift embeddable SDK |
| **UniPet** (ydyangdan) | 34 stars | Universal desktop pet for Codex, Claude Code, Hermes, OpenClaw, DeepSeek-TUI. Node.js + Electron. One stable localhost event protocol |
| **Peon Pet** (Luodian) | 2 stars | Desktop pet with `peon-ping` hook that reads `~/.claude/hooks/.state.json`. 6 pre-built animations per character (sleeping, waking, typing, alarmed, celebrate, annoyed). AI sprite-atlas generation prompt included |
| **AlterHQ `openpets.sh`** | 79 stars | Same as alterhq/openpets above; the `alterhq` fork is now the primary |

### How the agent triggers motions

The mechanism is **not** LLM tool-calls in the OpenAI API sense. Instead it is:

1. **Codex Pet format**: the Codex CLI itself maps internal session states (`thinking`, `tool-running`, `reviewing`, `success`, `failure`) to sprite rows. No external API call needed.
2. **Community wrappers** (CoPet, OpenPet, UniPet): They poll Codex/Claude session logs or receive MCP tool invocations — the agent's MCP tools explicitly call `pet.play('waving')`, `pet.event('success')`, etc.
3. **Web SDK**: `codex-pet-companion` exposes a clean JavaScript API: `pet.play('waving', { loop: false, returnTo: 'idle' })` — any web page can embed a pet and call these methods from agent-triggered JS.

**Bottom line for our use case**: The `codex-pet-companion` Web SDK is the **directly usable** piece — it's a single npm package + one `<codex-pet>` tag, and the `SpriteAnimator` API (`setState('running')`, `setAnimation('waving')`) is the exact "tool-call → preset motion" mapping we want.

---

## 2. Claude Code / "Cloud FM" Pattern

### What it actually is

**Claude FM** is Anthropic's 24/7 lo-fi YouTube radio stream for developers. The `/radio` slash command opens it in the default browser (or prints the URL on headless SSH). The stream plays human-composed lo-fi/ambient music, credits artists on-screen, and has pixel-art mascot animations in its YouTube overlays. **There is no open "LLM-triggers-preset-action" protocol in Claude FM.**

The musician agents — **Claudio Symphony** ([rmtbb/claudio-symphony](https://github.com/rmtbb/claudio-symphony), MIT, 3 stars) and **DJ Claude** ([p-poss/dj-claude](https://github.com/p-poss/dj-claude), AGPLv3, 2 stars) — are the real "preset action" pattern:

- **Claudio Symphony**: hooks into Claude Code's event system (tool calls, edits, sub-agent returns) and maps each event type to generative ambient tones. 36 presets. Live web console showing a constellation of animated orbs.
- **DJ Claude**: an MCP plugin for Claude Code with 20 MCP tools. Keyless tier: 22 preset music patterns (mood/genre/activity). Full Strudel-lang generative tier. Conductor mode orchestrates a full "jam session band" from one directive.

**The validated pattern** from both is:
> Claude Code hooks / MCP tools → event type → named preset name → play/set preset

That maps 1:1 to "agent tool-call → named animation → play animation" for a visual mascot. The hook→preset pipeline is proven and production-ready in the music domain.

---

## 3. Open-Source Pet / Mascot Frameworks Table

### Web-embeddable (priority: our pet lives on the web call page)

| Framework | Stars | Web-embeddable | LLM-drivable? | License | Notes |
|---|---|---|---|---|---|
| **`codex-pet-companion`** (wildcard) | — | ✅ Web Component / JS API | ✅ Via JS API `play()`, `setState()` | MIT | One `<codex-pet>` tag. **Closest match to our use case.** |
| **Live2D web runtimes** (avgjs/pixi-live2d, cubism-web) | — | ✅ Canvas / WebGL | ⚠️ Needs wrapper | MIT / Live2D license | Full expression system, rich SDK, heavy learning curve |
| **Rive** (rive-app) | industry | ✅ `@rive-app/webgl2`, canvas, lite | ✅ State machine API `fire()`, `setInput()` | Free tier, commercial | 120fps, smallest bundle for our use case, state-machine → animation name mapping is perfect |

### Desktop (also relevant: we could embed these API calls in our web runtime)

| Framework | Stars | Web-embeddable | LLM-drivable? | License | Notes |
|---|---|---|---|---|---|
| **CoPet** (ChanceYu) | 18 | ❌ Tauri desktop | ✅ Real-time agent events → reactions | MIT | Agent event → reaction mapping is exactly what we need, but desktop-only |
| **OpenPet** (X-T-E-R) | 49 | ❌ Tauri desktop | ✅ CLI + MCP + HTTP API | GPL-3.0 | CLI command `openpet-cli event think` / MCP tool call; clean API surface |
| **OpenPets** (alterhq) | 79 | ❌ macOS native | ✅ MCP server + plugins | MIT | MCP tools are the cleanest abstraction; macOS only |
| **Peon Pet** (Luodian) | 2 | ❌ Electron desktop | ✅ Hook-driven (reads `.state.json` every 200ms) | MIT | Simple hook protocol: file → animation |
| **UniPet** (ydyangdan) | 34 | ❌ Electron desktop | ✅ CLI / HTTP / WebSocket | MIT | `unipet state running "message"` — simple, web-embeddable companion |
| **N.E.K.O.** (Project-N-E-K-O) | 2K | ⚠️ Has web UI | ✅ Full agent + memory + plugin | Apache 2.0 | Over-engineered for our needs, but has Live2D + VRM + browser surfaces |
| **PetGPT** (JulesLiu390) | 101 | ❌ Desktop Electron | ✅ LLM-driven personality | — | Autonomous social agent pet, not event-driven |
| **AI-tamago** (ykhli) | 521 | ✅ Web (Next.js) | ✅ LLM-driven state | MIT | Tamagotchi: LLM generates both dialogue AND ASCII art animations |
| **petpet** (ppXD) | 98 | ❌ Tauri desktop | ✅ Multi-agent event-driven | MIT | XP from real token usage → evolution stages. Very playful |
| **Tamago.ai** (swarmclawai) | 0 | ✅ Electron/Next.js | ✅ Ollama Cloud | MIT | Pixel art CSS, Tamagotchi stats |

---

## 4. Recommended Format for the Yellow Sheep

### Decision matrix

| Format | Authoring from existing PNG art | Web runtime size | Animation expressiveness | LLM trigger mechanism | Authoring cost |
|---|---|---|---|---|---|
| **Sprite sheet** (bitmap / spritesheet.webp) | ✅ Highest — draw frames in PNG, tile into sprite sheet | ~10–50 KB | Discrete, limited | Frame row → animation name in JSON | Low if frames already exist |
| **Lottie** | ⚠️ Moderate — need to vectorize PNG | ~20–100 KB | Smooth, interpolated | `lottie.play('wave')` by segment label | Medium |
| **Live2D** | ❌ Low — requires Cubism SDK workflow, parts must be separated | ~1 MB+ | Highest (deformable mesh) | `motionManager.startMotion('idle')` | High |
| **Rive** | ⚠️ Moderate — need to import art into Rive editor | ~20–200 KB | High (state machine, interpolated) | `rive.fire('wave')` state machine input | Medium |

### Verdict for Yellow Sheep

**Start with a sprite-sheet / `codex-pet-companion` format**, for these reasons:

1. **Lowest authoring barrier**: If the Yellow Sheep already exists as 2D flat art, the sprite-sheet path just requires drawing/discovering a handful of keyframe PNGs, tiling them into a `1536 × 2288` (v2) WebP atlas, and writing a 10-line `pet.json`. No rigging, no SDK, no deformation work.

2. **`codex-pet-companion` is built for exactly this**: One `<codex-pet>` tag, `pet.play('wave')`, `pet.play('think')`, `pet.play('celebrate')`. The web SDK is ~4 KB. There is an explicit `SpriteAnimator` class if we want to skip the full pet framework and just drive the atlas directly.

3. **Web-native**: Since our mascot lives on a web call page (not a desktop), Rive's web runtime is an alternative, but Rive requires the Rive editor to author state machines — it does not accept arbitrary PNGs as inputs. For a flat 2D character, the sprite sheet is the lowest-friction path.

4. **Upgrade path**: Once the sprite-sheet format is working and we know which motions the agent actually needs, we can migrate to Rive (for smoother interpolated animations) or Live2D (for richer expressions) without changing the agent-facing API.

**Recommended motion list** (initial, proven useful from Codex pet / CoPet event mapping):
- `idle` — idle loop
- `thinking` / `working` — agent is processing
- `running` — actively executing tools
- `waiting` — awaiting user approval / input
- `success` / `celebrate` — task completed
- `failed` / `annoyed` — error state
- `waving` — greeting / session start

---

## 5. Verdict

**Mature, ready-to-integrate solution exists: `codex-pet-companion` (Web Component / JS SDK) + a Codex-pet-format sprite atlas.**

It is `npm install codex-pet-companion` → `<codex-pet>` on your page → `pet.play('wave')` from agent-triggered JavaScript. That's the full integration. Authoring the Yellow Sheep as a v2 sprite atlas (`pet.json + spritesheet.webp`) is a graphics task, not a software architecture task.

**Two-stop assembly plan:**
1. **Asset authoring** — draw the Yellow Sheep as a 6–9 frame animation sheet, tile into `1536 × 2288` WebP, write `pet.json`
2. **Agent bridge** — one lightweight JS function that maps agent tool-call types (tool_use → `running`, completion → `celebrate`, error → `failed`) to `pet.play(stateName)`. Expose this via a simple WebSocket or SSE endpoint from our agent runtime so the web call page can call it

**No framework changes needed** — just the sprite asset + 10 lines of glue code.

---

## Sources

| Source | URL |
|---|---|
| Codex TUI pets PR (merged 2026-05-12) | https://github.com/openai/codex/pull/21206 |
| Codex Pet Web SDK (wildcard/codex-pet-companion) | https://github.com/wildcard/codex-pet-companion |
| Minty Codex Pet — v2 atlas spec | https://github.com/Somnusochi/minty-codex-pet |
| OpenPet — CLI + MCP + HTTP API | https://github.com/X-T-E-R/OpenPet |
| CoPet — agent event → pet reaction | https://github.com/ChanceYu/CoPet |
| OpenPets (alterhq) — MCP server + plugins | https://github.com/alterhq/openpets |
| UniPet — universal agent pet | https://github.com/ydyangdan/UniPet |
| Peon Pet — hook-driven sprite animation | https://github.com/Luodian/peon-pet |
| DJ Claude — MCP preset action pattern | https://github.com/p-poss/dj-claude |
| Claudio Symphony — Claude Code hooks → generative tones | https://github.com/rmtbb/claudio-symphony |
| Claude FM / `/radio` explained | https://explainx.ai/blog/claude-code-radio-claude-fm-lofi-stream-guide-2026 |
| Rive web runtime docs | https://rive.app/docs/runtimes/web/web-js |
| Rive Parameters API | https://rive.app/docs/runtimes/web/rive-parameters |
| Live2D web embed (avgjs/pixi-live2d) | https://github.com/avgjs/pixi-live2d |
| AI-tamago — LLM-driven web pet | https://github.com/ykhli/AI-tamago |
| Codex Protocol v1 spec | https://github.com/openai/codex/blob/main/codex-rs/docs/protocol_v1.md |
| Mascot Bot — Rive + brand mascot tutorial | https://templates.mascot.bot/custom-brand-mascot-tutorial |
| N.E.K.O. — full LLM agent + avatar runtime | https://github.com/Project-N-E-K-O/N.E.K.O |
