# A2A + Multi-Harness Research — coding-vibe

> Written: 2026-07-23  
> Project: coding-vibe — two-tier AI coding companion

---

## (A) A2A Protocol Landscape (2026)

### Google Agent2Agent (A2A)

**Status: Real, v1.0, industry standard**

Google donated A2A to the Linux Foundation on June 23, 2025 (Open Source Summit NA).  
Governance body: **LF Agentic AI Foundation (AAIF)** — co-founded with Anthropic, Block, and OpenAI in December 2025 alongside MCP.  
TSC members: AWS, Cisco, Google, IBM, Microsoft, Salesforce, SAP, ServiceNow.

**v1.0 milestone** (April 9, 2026): 150+ organizations, 22,000+ GitHub stars, SDKs in Python, JavaScript, Java, Go, .NET.

**Agent Cards**: JSON metadata at `GET /.well-known/agent-card.json`, 14 fields (name, description, url, version, capabilities, skills, authentication, supportedInterfaces, signatures …). Primary discovery mechanism.

**Task lifecycle**: 8 states — `submitted → working → input-required / auth-required → completed / canceled / rejected / failed`. Terminal states are immutable; follow-ups create new Tasks in the same `contextId`. Three agent response modes: message-only, task-generating, hybrid.

**Adoption**: Microsoft (Azure AI Foundry, Semantic Kernel, .NET SDK), AWS (Amazon Bedrock AgentCore), IBM (merged competing ACP into A2A, Aug 2025), Salesforce, SAP, ServiceNow.

**Sources:**
- https://a2a-protocol.org/v1.0.0/specification/
- https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year
- https://lfaidata.foundation/communityblog/2025/08/29/acp-joins-forces-with-a2a-under-the-linux-foundations-lf-ai-data/

---

### MCP (Model Context Protocol)

**Status: Real, v1 spec, LF AAIF**

MCP is primarily a **tool/context protocol** (client-server: agent calls tool servers). It is not designed as peer-to-peer agent-to-agent, but Microsoft demonstrated in July 2025 that orchestrator ↔ specialist agent patterns can be composed over MCP using resumable streams, elicitation, sampling, and progress notifications.

**Relationship to A2A**: Complementary layers — MCP owns the vertical (agent → tools) layer, A2A owns the horizontal (agent → agent) layer. Both live under the same AAIF/Linux Foundation umbrella. Decision rule: use MCP when you control both sides and trust boundaries are shared; use A2A when agents cross ownership/trust boundaries.

**Key 2025–2026 updates**:
- SEP-1686 Tasks primitive (Amazon-authored): wraps MCP calls in a task lifecycle — closes part of the A2A gap
- Server-side agentic loops (Nov 2025): MCP servers can run their own LLM-driven loops
- LF AAIF donation (Dec 9, 2025): neutral governance; co-founders Anthropic, Block, OpenAI
- Scale: 97M+ monthly SDK downloads, 10,000+ active MCP servers as of early 2026

**Sources:**
- https://developer.microsoft.com/blog/can-you-build-agent2agent-communication-on-mcp-yes
- https://redis.io/blog/mcp-vs-a2a-which-protocol-do-you-need
- https://modelcontextprotocol.io/seps/1686-tasks

---

### Other Standards

| Protocol | Status | Adopted in Prod? |
|---|---|---|
| **A2A** | Real — v1.0, 150+ orgs | ✅ Azure AI Foundry, Bedrock, Salesforce |
| **MCP** | Real — 97M downloads, 10K servers | ✅ All major providers |
| **ACP (IBM)** | **Retired** — merged into A2A Aug 2025 | Superseded |
| **AGNTCY** | Real — LF project, 4 components (Elixir/Python/Go/Rust) | ✅ AGNTCY Identity; Directory functional |
| **ANP (Alibaba)** | Real but early — W3C-track, arXiv white paper | ⚠️ No confirmed external production adopters |
| **AIPF (IETF)** | Very early — Internet-Draft, expires Jan 2027 | ❌ Not an RFC yet |

**ACP**: IBM's competing protocol had a genuine foothold (BeeAI platform, REST/OpenAPI semantics, `await` primitive). Merged into A2A in record time — 5 months from launch to formal archive.

**AGNTCY**: Occupies infrastructure/registry/identity layer (OASF schema, Agent Directory, SLIM messaging), complementary to A2A. Real and actively maintained — not vaporware.

**ANP**: Alibaba's "HTTP of the Agentic Web" — architecturally ambitious (W3C DID, meta-protocol negotiation) but sits at draft status with no confirmed production adopters beyond Alibaba as of June 2026.

**Sources:**
- https://github.com/agntcy/README
- https://datarekha.com/agentic-ai/agent-protocols/
- https://dreaming.press/posts/a2a-vs-acp-vs-agntcy-agent-interop-protocols.html
- https://datatracker.ietf.org/doc/draft-zahed-agent-comm-framework/

---

## (B) Per-Harness Programmatic Integration Matrix

For each harness: can a receptionist spawn it as a subprocess, send a task, and get a result programmatically — or is it GUI-only?

| Capability | Claude Code | Cursor | Codex CLI | Aider | Gemini CLI |
|---|---|---|---|---|---|
| **Headless CLI** | ✅ `claude -p "..."`<br>— non-interactive, stdout result, exits | ✅ `agent -p --force "..."`<br>— applies changes, exits | ✅ `codex exec "..."`<br>— stdout=final msg, stderr=live progress | ✅ `aider --message "..." --yes --no-stream`<br>— single-shot, exits | ✅ `gemini -p "..."`<br>— exits after response |
| **Exit code / clean return** | ✅ Exit 0 on completion | ✅ Exits after run | ✅ Exit 0 on completion | ✅ Single-shot exits | ✅ Exits after response |
| **Stdin piping** | ✅ `cat f \| claude -p "..."` | ✅ Supported | ✅ `codex exec` reads stdin | ✅ `--message-file` / stdin | ✅ `echo "..." \| gemini -p` |
| **JSON structured output** | ✅ `--output-format json`<br>`--output-format stream-json` | ⚠️ Text only<br>(parse stdout) | ✅ `--json` (JSONL, line-by-line) | ❌ No JSON flag<br>(inspect `git diff` instead) | ✅ `--output-format json`<br>`--output-format stream-json` |
| **Python SDK** | ✅ `claude-agent-sdk`<br>`query()`, `ClaudeSDKClient`,<br>`AgentDefinition`, `@tool` | ❌ | ✅ `openai-codex`<br>`Codex`, `AsyncCodex`,<br>`Sandbox`, `thread.run()` | ✅ `aider.coders.Coder`,<br>`aider.models.Model` | ✅ `google.genai`<br>Interactions API:<br>`client.interactions.create()` |
| **TypeScript SDK** | ✅ `@anthropic-ai/claude-agent-sdk` | ✅ `@cursor/sdk`<br>(local + cloud, ~212K downloads/wk) | ✅ `@openai/codex-sdk` | ❌ | ✅ `@lrilai/gemini-cli-sdk`<br>+ `@ketd/gemini-cli-sdk` |
| **MCP client** | ✅ Native<br>(`mcpServers` in `settings.json`) | ✅ Native<br>(`.cursor/mcp.json` or `mcp.json`) | ✅ Native<br>(`codex mcp add …`) | ❌ No native<br>(community wrappers only) | ✅ Native<br>(3 transports: stdio / SSE / HTTP) |
| **MCP server** | ❌ No native<br>(community: `steipete/claude-code-mcp`) | ❌ No native<br>(community MCP bridges exist) | ✅ Experimental<br>(`codex mcp-server`) | ❌ | ❌ |
| **Sandbox / isolation** | ✅ Sandbox (default on; disable via `settings.json`) | ✅ VMs (cloud mode via Cloud Agents API) | ✅ `--sandbox read-only / workspace-write / full-access` | ❌ OS-level only | ✅ Cloud agents: Linux sandbox<br>(7-day inactivity expiry) |
| **Auto-approval / unattended** | ✅ `--permission-mode auto`<br>`--permission-mode acceptEdits` | ✅ `--force` / `--yolo` | ⚠️ Must set `--ask-for-approval never`<br>explicitly | ✅ `--yes` flag | ⚠️ Approval prompts<br>(opt-out via config) |
| **Multi-turn programmatic** | ✅ `ClaudeSDKClient`<br>`--resume <id>` | ✅ `@cursor/sdk` streaming | ✅ SDK threads, `thread.run()` multi-turn | ⚠️ One-shot best<br>(multi-turn via `Coder` API) | ⚠️ Draft PR for stdin multi-turn<br>(use SDK for production) |
| **Subprocess spawn-friendly** | ✅ CLI + SDK both work | ✅ `agent -p` is subprocess-safe | ✅ `codex exec` is subprocess-safe | ✅ Fully parallelizable processes | ✅ Subprocess + SDK both work |
| **Notable gap** | No `--yes` flag (use `--permission-mode`); no native MCP server | No official MCP server; community bridges only | MCP tool calls auto-cancel in `exec` mode; no `--quiet` flag | No JSON output; no native MCP | Approval prompts require explicit opt-out; CLI has no OS sandbox |

**Sources:**
- Claude Code: https://code.claude.com/docs/en/headless · https://code.claude.com/docs/en/agent-sdk/python.md · https://code.claude.com/docs/en/mcp · https://code.claude.com/docs/en/hooks
- Cursor: https://cursor.com/docs/cli/headless · https://cursor.com/docs/sdk/typescript · https://cursor.com/docs/cloud-agent/api/endpoints · https://cursor.com/docs/mcp
- Codex CLI: https://developers.openai.com/codex/noninteractive · https://pypi.org/project/openai-codex · https://developers.openai.com/codex/mcp · https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs
- Aider: https://aider.chat/docs/scripting.html · https://aider.chat/docs/config/options.html · https://github.com/Aider-AI/aider/pull/3767
- Gemini CLI: https://google-gemini.github.io/gemini-cli/docs/cli/headless.html · https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md · https://ai.google.dev/gemini-api/docs/agents · https://ai.google.dev/gemini-api/docs/code-execution

---

## (C) Recommendation for coding-vibe

### Current architecture

Receptionist harness reads delegation files on disk, toggles internal state (CEO ↔ CS), and delegates tasks to itself. Both roles are played by the same Claude Code harness.

---

### Tradeoff analysis

**Option 1 — Keep same-harness hook-toggle (current approach)**

| Factor | Verdict |
|---|---|
| Latency | Best — no process spawn overhead; internal delegation is one API call |
| Complexity | Lowest — no A2A adapter, no transport layer, no task state machine |
| Multi-harness flexibility | **None** — locked to one model family (Anthropic); cannot run Codex / Gemini in parallel |
| Failure isolation | **Weak** — if the harness crashes or hangs, both roles die together |
| Code complexity | Low — delegation file + hook + one `claude -p` or SDK call |

**Option 2 — Standalone receptionist + subprocess orchestration (recommended)**

Receptionist is a standalone Python/TypeScript process that `subprocess.Popen`s engineer harnesses, passes tasks via stdin/stdout, and parses results.

| Factor | Verdict |
|---|---|
| Latency | Good — ~300–500ms subprocess spawn per engineer; no HTTP round-trip; well within interactive UX limits |
| Complexity | Moderate — one harness per engineer type; stdio transport layer; exit code + JSON parsing; no A2A spec implementation needed |
| Multi-harness flexibility | **High** — mix Claude Code + Cursor + Codex + Aider + Gemini in parallel; different models, working dirs, approval modes |
| Failure isolation | **Strong** — if engineer A crashes, receptionist restarts it; engineer B continues |
| Code complexity | Moderate — small orchestrator (~200–300 LOC) handles spawn, timeout, JSON parsing, retry |

**Option 3 — Full A2A protocol adoption**

| Factor | Verdict |
|---|---|
| Latency | Higher — HTTP round-trip per message; A2A task lifecycle adds overhead |
| Complexity | **Highest** — implement or adopt A2A server on each engineer harness (none ship one natively); implement A2A client in receptionist; handle Agent Card discovery, task state machine, signature verification |
| Multi-harness flexibility | Highest — true peer-to-peer, cross-org, cross-ownership |
| Failure isolation | Strong — A2A task lifecycle has explicit `failed` state; retry is protocol-native |
| Code complexity | High — 500+ LOC of A2A plumbing before any business logic |
| Readiness | **Premature** — no coding harness ships a production A2A adapter as of mid-2026; you'd own the entire integration layer |

---

### Concrete implementation shape (Option 2)

```
coding-vibe/
├── receptionist.py              # standalone process
│   ├── read delegation files from /tmp/coding-vibe/
│   ├── dispatch per engineer type:
│   │   ├── claude -p "<task>" --output-format json
│   │   ├── codex exec --json --sandbox workspace-write "<task>"
│   │   ├── aider --message "<task>" --yes --no-stream
│   │   └── gemini -p "<task>" --output-format json
│   ├── parse JSON/stdout, extract result
│   └── write result back to delegation file
└── /tmp/coding-vibe/
    ├── receptionist.flag        # "idle" | "awaiting-approval"
    ├── engineer.flag            # "idle" | "working"
    └── task.json                # { task, context, result }
```

**Upgrade path to A2A:** When any harness ships a production A2A server adapter, the stdio transport layer in `receptionist.py` is the natural seam to swap in. The delegation-file protocol and orchestrator logic do not change.

---

### Verdict

| | Keep same-harness | **Subprocess orchestration** | Full A2A |
|---|---|---|---|
| Effort to implement | 0 (already done) | ~1–2 days | 2–4 weeks |
| Multi-harness support | ❌ | ✅ | ✅ |
| Failure isolation | ❌ | ✅ | ✅ |
| Latency | Best | Good | Worse |
| Ecosystem alignment | Internal only | **All 5 harnesses support this today** | No harness supports this today |
| Upgrade path | Rewrite required | Swap stdio → A2A later | Already there |

**Pick Option 2 — standalone receptionist + subprocess stdio orchestration.**

All five harnesses support the subprocess pattern today. Adding a new engineer type is a one-line config change. Failure isolation is built in. When A2A adapters eventually ship on these harnesses, the stdio transport layer is the natural seam to upgrade — no orchestrator rewrite needed.

A2A is a real, v1.0 standard with genuine industry momentum; it is not vaporware. But none of the five harnesses ship a production A2A adapter today, and building one yourself before validating the core CS↔CEO delegation premise is premature engineering.
