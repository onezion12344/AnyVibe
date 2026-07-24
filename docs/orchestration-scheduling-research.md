# Orchestration & Scheduling Research: Harness-Level Multi-Agent Layers

**Written:** 2026-07-24
**Scope:** Tools that spawn/coordinate MULTIPLE instances of coding agent harnesses (Claude Code, Codex CLI, Cursor, Gemini CLI) and how they implement inter-agent communication. Prior art for coding-vibe's receptionist → engineer delegation pattern.

---

## PART 1 — OpenOPC: Local Prior Art (unchanged from v1)

See the original Part 1 for full analysis. The OpenOPC findings are still relevant and carried forward into the synthesis table. Key points recap:

| Concept | File | Lines |
|---|---|---|
| DAG scheduler | `opc/layer2_organization/task_graph.py` | 16–120 |
| Role-queue dispatch | `opc/layer2_organization/company_runtime.py` | 1165–1500 |
| Dispatcher wake event | `opc/layer2_organization/company_mode.py` | 1506–1511 |
| Turn mode classifier (6 modes) | `opc/layer2_organization/turn_mode.py` | 56–161 |
| Phase state machine (18 states) | `opc/layer2_organization/phase.py` | 1–100+ |
| Comms mailbox (file-backed) | `opc/layer2_organization/comms.py` | 1–80+ |
| Central orchestrator | `opc/engine.py` | 9057–9412 |

OpenOPC has **no dedicated triage/receptionist agent** as a first-class concept. The closest is a manager role in `DELEGATE` turn mode. The Architect→Builder→Reviewer chain it runs is the right CEO-level abstraction for coding-vibe's engineer role.

---

## PART 2 — Harness-Level Orchestration Layers

### 2.1 Claude Code Native: Subagents + Agent Teams + Dynamic Workflows

**Sources:**
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/agent-teams
- https://code.claude.com/docs/en/workflows
- https://code.claude.com/docs/en/agent-sdk/subagents.md
- https://mintlify.com/sanbuphy/claude-code-source-code/llms.txt (architecture docs)
- https://www.mindstudio.ai/blog/claude-code-agent-teams-vs-sub-agents
- https://y-agent.github.io/inside-claude-code/07-multi-agent-orchestration.html

#### Topology

Claude Code supports **three distinct multi-agent modes** at different granularity levels:

**Subagents (in-session, lowest overhead):**
```
MAIN AGENT
├── Sub-agent A (in-process, AsyncLocalStorage context)
├── Sub-agent B (in-process, AsyncLocalStorage context)
└── Sub-agent C (fork process, fresh messages[])
```
- `default` mode: same process, context isolated via `AsyncLocalStorage`. Lowest overhead, shared state.
- `fork` mode: child process gets fresh `messages[]`, shared file cache, isolated cwd. Process boundary = failure isolation.
- Communication back to parent: return value (summary). No persistent message bus.

**Agent Teams (feature-gated, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`):**
```
TEAM LEAD (one session)
├── Teammate A (own context window, own messages[])
├── Teammate B (own context window, own messages[])
└── Teammate C (own context window, own messages[])
```
- Each teammate is a **separate Claude Code session** with its own context window.
- Teammates **communicate directly with each other**, not just through the lead.
- One session is the team lead: coordinates work, assigns tasks, synthesizes results.
- Team lifecycle: `Agent` tool with `team_name` parameter (now deprecated; auto-spawns with env var).
- **Known limitations**: session resumption, task coordination, and shutdown behavior.

**Dynamic Workflows (paid plans, v2.1.154+):**
```
Orchestrator script (Claude-written, re-runnable)
├── Wave 1: Sub-agents A, B, C (parallel)
├── Wave 2: Sub-agents D, E (depend on Wave 1 results)
└── Wave 3: Synthesis agent
```
- Claude writes and maintains the orchestration script.
- Explicit dependency graph between agent tasks.
- Designed for codebase audits, large migrations, cross-checked research.

#### Inter-Agent Communication Mechanism

| Channel | Mechanism |
|---|---|
| Subagent → parent | Return value / summary (structured) |
| Teammate → teammate | `SendMessageTool` (agent-to-agent messages) |
| Lead → teammates | `TaskCreate` / `TaskUpdate` on shared task board |
| Team lifecycle | `TeamCreate` / `TeamDelete` tools (deprecated in v2.1.178) |

The **shared task board** (`TaskCreate`/`TaskUpdate`) is the primary coordination primitive for agent teams. Hooks fire on `TaskCreated`, `TaskCompleted`, `TeammateIdle` events.

#### Who Schedules / Decides Next Agent

- **Subagents**: Parent agent decides (LLM chooses when to spawn).
- **Agent Teams**: Team lead decides (LLM-based assignment from lead's context).
- **Dynamic Workflows**: Claude-written script decides (deterministic wave ordering based on dependency graph).

#### How Results Return

- Subagents: return summary object back to parent's context.
- Agent Teams: results added to shared task board; lead synthesises.
- Dynamic Workflows: results flow through wave dependency chain.

#### Triage / Receptionist Suitability

The **team lead in Agent Teams** is the closest native analog to a receptionist. However:
- Feature-gated (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`), not production-stable.
- Team lead is an LLM — same 2-hop latency as any LLM-router.
- No explicit "triage" role; lead assigns tasks by natural-language understanding.
- Known resumption and shutdown gaps make it risky for a voice UAT loop.

---

### 2.2 Claude Swarm (parruda/claude-swarm)

**Sources:**
- https://github.com/parruda/claude-swarm (⭐ 1,715)
- https://badge.fury.io/rb/claude_swarm
- https://awesome.re (listed in Awesome Claude Code)

#### Topology

**Tree / hierarchical MCP topology.** YAML-defined:

```yaml
# From repo README (v1 architecture)
swarm:
  topology: tree
  root: orchestrator
  agents:
    - name: frontend
      parent: orchestrator
      role: frontend-developer
      mcp_servers: [filesystem, github]
    - name: backend
      parent: orchestrator
      role: backend-developer
      mcp_servers: [postgres, redis]
    - name: tester
      parent: orchestrator
      role: qa-engineer
```

Each agent node has:
- A **role** (determines system prompt / expertise)
- A **parent** (forms the tree)
- **MCP server connections** (scoped tool access per role)
- A **directory context** (scoped filesystem root)

**v2 (SwarmSDK):** Single-process architecture, better performance, more features. Recommended for new projects.

#### Inter-Agent Communication Mechanism

**MCP-based message passing** through a shared MCP server. Each Claude Code instance in the swarm connects to the swarm coordinator via MCP. Messages are forwarded through the coordinator, which routes them to the target agent's MCP session.

The tree structure means:
- Child → parent: direct MCP call
- Sibling → sibling: routed up to common ancestor and back down
- Root → any: direct MCP call

No shared file queue; no git worktree isolation built-in. Communication is entirely through the MCP layer.

#### Who Schedules / Decides Next Agent

The **orchestrator** (root node) schedules work to children. Leaf agents complete their subtask and report back. The routing is **YAML-static** — the tree topology is defined at startup, not dynamically adapted at runtime.

#### How Results Return

Child agents return results via MCP message back to parent. Parent aggregates and synthesises. No structured result envelope beyond the message content.

#### Triage / Receptionist Suitability

The **orchestrator node** is the triage agent. However:
- No dynamic routing — the tree is static YAML. A new task type requires a new tree branch.
- MCP round-trip per message adds latency (~100–300ms per hop).
- No fast-path for low-complexity requests.
- v2 is single-process — shared crash domain.

---

### 2.3 Claude Squad (smtg-ai/claude-squad)

**Sources:**
- https://dev.to/arash/series/claude-squad (DEV Community series)
- https://github.com/smtg-ai/claude-squad

#### Topology

**Peer-to-peer via tmux + git worktree isolation.** Each agent runs in its own tmux pane with its own git worktree:

```
coding-vibe/
├── main/          ← agent A worktree
├── feature-x/     ← agent B worktree
├── fix-bug-y/      ← agent C worktree
└── .claude-squad/ ← coordination state
```

Key isolation property: **each agent has its own branch and working tree**, so agents never overwrite each other's files. They merge back via standard git flow.

#### Inter-Agent Communication Mechanism

- **TUI (Terminal UI)** for human oversight — the human is in the loop for coordination.
- **Auto-accept mode**: agents run without human confirmation, suitable for overnight work.
- Coordination state stored in `.claude-squad/` directory.
- **No persistent message bus between agents.** Communication is indirect: agents write to their worktree; the human or CI system notices and coordinates.
- Git worktree provides the isolation; tmux provides the session management.

#### Who Schedules / Decides Next Agent

**Human-in-the-loop by default** (via the TUI). Auto-accept mode delegates to the agents themselves (they decide when to proceed). No LLM-based orchestrator — agents work in parallel and the human merges.

#### How Results Return

Each agent works in its own worktree. Results are git commits in their branch. The human (or auto-accept mode) merges branches. There is no structured result delivery mechanism — it's a **git-driven integration model**.

#### Triage / Receptionist Suitability

Claude Squad is **not a receptionist pattern at all** — it's a parallel execution harness for humans who want to run multiple Claude Code sessions simultaneously. The human is the coordinator. No relevance to a low-latency voice loop.

---

### 2.4 Claude Flow / Swarm (ruvnet/claude-flow)

**Sources:**
- https://github.com/ruvnet/claude-flow (⭐ 65,000)
- https://www.npmjs.com/package/@claude-flow/swarm (v3 ADR-003)
- https://ruvnet.github.io/ruflo/docs/user-guide-v2.html

#### Topology

**4 topology types** in v3 (`UnifiedSwarmCoordinator`):
```
topology.type = "mesh"        | "hierarchical" | "centralized" | "hybrid"
```

Default: **15 agents**, configurable up to 100+. Key components:

| Component | Role |
|---|---|
| `UnifiedSwarmCoordinator` | Canonical engine — routes tasks to agents, tracks workload |
| `QueenCoordinator` | Hive-mind intelligence — strategic task decomposition, capability-based delegation |
| `AttentionCoordinator` | Attention mechanisms (flash attention, multi-head, MoE routing) |
| `FederationHub` | Cross-swarm coordination, ephemeral agent spawning with TTL |
| `ConsensusEngines` | Raft, Byzantine (2/3 supermajority), Gossip protocols |

**QueenCoordinator** is the strategic brain: it decomposes high-level tasks into subtasks and delegates to agents based on capability matching.

#### Inter-Agent Communication Mechanism

**Internal message bus** (`SwarmCoordinatorMessageBus`). Agents register as publishers/subscribers. Messages are typed events routed by topic. Cross-swarm messages go through `FederationHub`.

**File-based state**: agent memory, task queue, and consensus state are persisted. `FederationHub` supports ephemeral agents with TTL-based auto-cleanup.

No MCP dependency for intra-swarm comms. MCP is used for tool calls from agents to external services.

#### Who Schedules / Decides Next Agent

The **QueenCoordinator** decides:
1. Ingest user task
2. Decompose into subtasks (strategic analysis)
3. Match subtasks to agents by capability profile
4. Dispatch to agents in parallel waves
5. Collect results, run consensus if needed
6. Synthesise final answer

The `UnifiedSwarmCoordinator` handles the actual dispatch loop with `<100ms` coordination overhead.

#### How Results Return

Agent results flow back through the message bus. The `QueenCoordinator` aggregates. Consensus algorithms (`ConsensusEngines`) can be applied when multiple agents produce conflicting results.

#### Triage / Receptionist Suitability

The **QueenCoordinator** is a sophisticated orchestrator but it is:
- TypeScript-only, designed for general multi-agent workflows, not voice-optimized.
- The decomposition step is an LLM call — same routing latency tax as other LLM-routers.
- Performance target (<100ms coordination) refers to dispatch, not end-to-end task completion.
- 15-agent default is over-engineered for a 2-tier CS→CEO pattern.

---

### 2.5 Conductor (run-multiple-claude-code-sessions)

**Sources:**
- https://github.com/runmymind/conductor (referenced in search results)
- Search result snippet: "Run multiple Claude Code sessions in parallel — In Conductor, the unit of independent Claude Code work is a workspace."

#### Topology

**Workspace-per-task model.** Each parallel task gets its own workspace with:
- Own git branch
- Own working tree
- Own setup context
- Own terminal
- Own diff view
- Own pull request path

```
Conductor
├── Workspace A (branch: feature/x, Claude Code session)
├── Workspace B (branch: fix/y, Claude Code session)
└── Workspace C (branch: refactor/z, Claude Code session)
```

Also documented for **Codex sessions**: "Run multiple Codex sessions in parallel — several Codex tasks moving at the same time without one task taking over."

#### Inter-Agent Communication Mechanism

**Git + filesystem isolation.** Workspaces do not share a message bus. Communication is:
- Git branch merges (PRs)
- Filesystem (workspace output files)
- Conductor's own state tracking (which workspace is running what)

No shared task queue visible from search results.

#### Who Schedules / Decides Next Agent

Human creates workspaces; Conductor launches Claude Code/Codex in each. Scheduling is **human-driven**, not LLM-driven.

#### How Results Return

Each workspace produces a branch + diff. Conductor surfaces the diffs. Merge is manual or PR-based.

#### Triage / Receptionist Suitability

Conductor is a **parallel execution tool, not an orchestrator**. No receptionist role. Not applicable to coding-vibe's pattern.

---

### 2.6 vibe-kanban (nobodyet / BloopAI)

**Sources:**
- https://github.com/nobodyet/vibe-kanban (fork of BloopAI/vibe-kanban)
- https://www.vibekanban.com/
- https://github.com/BloopAI/vibe-kanban

#### Topology

**Kanban-board-driven agent coordination.** The kanban board is the central state store. Agents are assigned to columns/cards:

```
TODO ─────► IN PROGRESS ─────► IN REVIEW ─────► DONE
   [agent A]     [agent B]         [agent C]
```

Supports Claude Code, Gemini CLI, Codex, Amp, and other coding agents.

#### Inter-Agent Communication Mechanism

**Kanban board state + hooks.** When an agent completes a card, the board state updates and triggers the next agent. The board is the shared state store — not a message bus, but a state machine. OpenOPC cites BloopAI/vibe-kanban as inspiration for its own kanban-centered work management.

#### Who Schedules / Decides Next Agent

The **kanban board state machine** + **agent assignment rules**. When a card moves to `IN PROGRESS`, the assigned agent picks it up. When it moves to `IN REVIEW`, the reviewer agent is triggered. Rules are configured per board.

#### How Results Return

Agent work is persisted to the card (description, diff, comments). Next agent in the pipeline reads the card state and the file changes.

#### Triage / Receptionist Suitability

The board's **"new card" event** acts like a triage trigger — but it is a human who creates the card. There is no autonomous triage agent. The kanban metaphor is good for human-visible work but does not solve the automated triage problem.

---

### 2.7 Claude Code Router / CCR / ccmanager

**Finding:** No verifiable, maintained "Claude Code Router" or "ccmanager" project was found in the search results. The search returned general multi-agent orchestration results but no specific project under those names. ⚠️ Any project with this name may be a small personal tool without a stable GitHub presence. No reliable source URLs available.

---

### 2.8 Anthropic Engineering: Multi-Agent Research System

**Source:**
- https://www.anthropic.com/engineering/how-we-built-our-multi-agent-research-system

#### Topology

**Orchestrator-worker pattern** with parallel sub-agent spawning. The published architecture:

```
User query
    │
    ▼
Orchestrator agent (plans research process)
    │
    ├──► Sub-agent A (parallel web search)
    ├──► Sub-agent B (parallel web search)
    ├──► Sub-agent C (parallel file/workspace search)
    └──► Sub-agent D (parallel Google Workspace search)
    │
    ▼
Synthesizer (aggregates results)
```

The orchestrator agent:
1. Plans a research decomposition based on the user query.
2. Uses a **tool to create parallel sub-agents** (same pattern as Claude Code's `TaskCreate`).
3. Waits for all sub-agents to complete.
4. Evaluates result quality.
5. Spawns follow-up agents if gaps are found.
6. Synthesises a final answer.

#### Inter-Agent Communication Mechanism

**Tool-based spawning + return values.** The orchestrator calls a tool (function call) that spawns a sub-agent. The sub-agent runs independently and returns its results. The orchestrator collects results via tool return values — no shared message bus, no persistent queue.

Key design choice from the post: sub-agents are **stateless workers** — each is spawned fresh for a subtask and returns a summary. No persistent agent identity across turns.

#### Who Schedules / Decides Next Agent

The **orchestrator agent** (LLM) decides. It plans the decomposition and uses tool calls to create and assign work to sub-agents. The orchestrator may iteratively spawn new sub-agents based on gap analysis.

#### How Results Return

Sub-agent results are returned as tool call results to the orchestrator. The orchestrator evaluates quality and decides whether to accept, re-run, or spawn follow-up agents. Final answer is the orchestrator's response to the user.

#### Triage / Receptionist Suitability

The orchestrator pattern is **directly applicable to coding-vibe**. The orchestrator = receptionist/CS, sub-agents = engineers. Key insights from Anthropic's engineering:
- Sub-agents should be **stateless workers** — no persistent identity needed per task.
- **Quality evaluation** before accepting results — the orchestrator checks completeness, not just "done."
- **Iterative gap-filling** — if the first wave of agents doesn't cover the problem, spawn follow-ups.
- The orchestrator always returns to the user — the CS→CEO→CS callback loop is exactly this pattern.

---

### 2.9 am-will/swarms — Multi-Agent Orchestration for Claude Code and Codex

**Sources:**
- https://github.com/am-will/swarms (⭐ 208)

#### Topology

**Orchestrator + explicit dependency graph + parallel waves:**

```bash
# From README
swarms plan <task_description>    # LLM generates dependency graph
swarms run                         # Execute in parallel waves
swarms verify                      # Orchestrator checks all results
```

- Plan phase: LLM decomposes task and builds explicit dependency graph.
- Run phase: execute independent tasks in parallel waves (wave 1 → wave 2 after wave 1 completes).
- Verify phase: orchestrator reviews all results for completeness.

#### Inter-Agent Communication Mechanism

**CLI stdio + shared state directory.** Each agent is a spawned Claude Code or Codex CLI process. The orchestrator reads/writes task state from a shared directory. No MCP, no message bus — pure filesystem + CLI stdio.

#### Who Schedules / Decides Next Agent

The **orchestrator** (a Claude Code or Codex CLI instance) decides:
- Plan phase: LLM generates dependency graph.
- Wave execution: deterministic order (wave N only starts when all wave N-1 tasks are complete).
- Verify phase: LLM evaluates whether all results are acceptable.

#### How Results Return

Each agent writes its result to stdout (captured by the orchestrator). The orchestrator aggregates and synthesises. Verification is a separate LLM pass.

#### Triage / Receptionist Suitability

The plan phase is **exactly a triage step** — the LLM classifies the task into subtasks with dependencies. However:
- The triage is done once upfront, not dynamically per incoming voice turn.
- No callback-when-done pattern — the orchestrator waits for all waves.
- CLI spawn per agent (~300–500ms overhead per spawn).

---

### 2.10 OpenAI Codex Multi-Task / Swarm Patterns

**Sources:**
- https://github.com/openai/codex (discussion #22749 — "Orchestration for parallel project-level coordination")
- https://www.youtube.com/watch?v=... (Net Ninja tutorial #11 — Running Tasks in Parallel)

#### Topology

Codex has **two relevant patterns**:

**Codex CLI parallel tasks:** `codex exec` can run multiple tasks. The GitHub discussion #22749 proposes explicit orchestration for parallel project-level work. As of the search, this is a **proposal**, not yet shipped.

**Codex Cloud:** OpenAI's hosted Codex supports task-based orchestration. Tasks are created via API and run asynchronously. Status is polled via task ID.

#### Inter-Agent Communication Mechanism

- Codex CLI: no built-in inter-agent comms; each `codex exec` call is isolated.
- Codex Cloud: REST API for task creation + polling for status. No push notifications.

#### Who Schedules / Decides Next Agent

- CLI: user scripts or external orchestrator.
- Cloud: user (or external orchestrator) creates tasks via API.

#### How Results Return

- CLI: stdout of each `codex exec` call.
- Cloud: API response on polling.

#### Triage / Receptionist Suitability

Codex has **no built-in receptionist or triage agent**. The orchestration proposal (#22749) is exactly the gap coding-vibe could fill.

---

## PART 3 — Synthesis

### 3.1 Comparison Table: Harness-Level Orchestration Layers

| Project | Topology | Comms Mechanism | Scheduler | Result Return | Triage/Receptionist |
|---|---|---|---|---|---|
| **Claude Code Subagents** | Star (parent→children, in-process or fork) | Return value / `SendMessageTool` | Parent LLM decides when to spawn | Return summary to parent | ⚠️ Parent is ad-hoc, not dedicated triage |
| **Claude Code Agent Teams** | Star (team lead→teammates, separate sessions) | `SendMessageTool` + shared task board (`TaskCreate`/`TaskUpdate`) | Team lead LLM assigns tasks | Shared task board + team lead synthesis | ⚠️ Lead ≈ triage but experimental, 2-hop latency |
| **Claude Code Dynamic Workflows** | DAG waves (Claude-written orchestration script) | Dependency graph + wave ordering | Claude-written script (deterministic) | Wave-by-wave result chain | ❌ No dynamic triage |
| **Claude Swarm (parruda)** | Tree/YAML-defined, MCP-based | MCP message passing (tree-routed) | Static YAML tree; root→child assignment | MCP message back to parent | ⚠️ Root = triage but static topology, no dynamic routing |
| **Claude Squad (smtg-ai)** | Peer (tmux panes, git worktree isolation) | Git branches + TUI | Human (or auto-accept mode) | Git branch + merge | ❌ Human is coordinator |
| **Claude Flow (ruvnet)** | Mesh/hierarchical/hybrid (4 types) | Internal message bus + FederationHub | `QueenCoordinator` (strategic LLM) + `UnifiedSwarmCoordinator` | Message bus aggregation + consensus | ⚠️ QueenCoordinator ≈ triage but over-engineered for 2-tier |
| **Conductor** | Star (human creates workspaces) | Git branches + workspace files | Human | PR/diff per workspace | ❌ Human is coordinator |
| **vibe-kanban** | Kanban state machine (board drives routing) | Kanban board state + hooks | Board state machine + assignment rules | Card state + file diffs | ⚠️ "New card" ≈ triage trigger but human-driven |
| **Anthropic Research** | Star (orchestrator + parallel workers) | Tool call return values (stateless workers) | Orchestrator LLM (gap-analysis iterative) | Tool return → orchestrator synthesis | ✅ Orchestrator ≈ triage; explicitly designed for this pattern |
| **am-will/swarms** | Wave DAG (plan → wave1 → wave2 → verify) | Filesystem + CLI stdio | Orchestrator LLM (plan phase) | CLI stdout aggregation + LLM verify | ⚠️ Plan phase = triage but static once planned |
| **Codex Cloud** | Star (API-driven task pool) | REST API polling | User / external orchestrator | API response | ❌ No triage |

### 3.2 How These Handle a Dedicated Triage/Receptionist Agent

| Project | Triage as First-Class? | How it maps to CS→CEO |
|---|---|---|
| **Claude Code Subagents** | ❌ | Parent agent does everything — no role separation |
| **Claude Code Agent Teams** | ⚠️ Partial | Team lead ≈ CS, teammates ≈ engineers; but experimental + 2-hop latency |
| **Claude Swarm** | ⚠️ Partial | Root = CS, children = engineers; but static YAML tree |
| **Claude Flow** | ⚠️ Partial | QueenCoordinator = CS, worker agents = engineers; over-engineered |
| **Anthropic Research** | ✅ Closest match | Orchestrator = CS (plans + evaluates quality), workers = engineers (stateless, parallel) |
| **am-will/swarms** | ⚠️ Partial | Plan phase = CS, wave agents = engineers; static DAG once planned |
| **All others** | ❌ | No triage concept |

**Anthropic's own system is the closest direct match to coding-vibe's CS→CEO pattern.** Their orchestrator explicitly: plans decomposition, spawns parallel workers, evaluates result quality, fills gaps, and returns to the user. The "callback when done" is the orchestrator's response after synthesis.

### 3.3 Where These Are Weak for a Low-Latency Voice Receptionist

1. **All LLM-routers have a mandatory inference hop.** Claude Code Agent Teams, Claude Swarm, Claude Flow, am-will/swarms, and Anthropic Research all require an LLM call before any worker is dispatched. For a voice CS handling "status check" queries in <500ms, this is a hard floor. No framework offers a deterministic fast-path.

2. **No framework is voice-native.** None handle barge-in, interim audio, silence detection, or real-time audio buffering. The voice layer is an external concern to all of these.

3. **Claude Code Agent Teams is experimental.** Known gaps around session resumption and shutdown. Unsuitable as a dependency for a voice UAT where crashes = lost user calls.

4. **Claude Swarm's static YAML tree cannot adapt to new task types at runtime.** Every new task category requires a YAML edit and restart. A voice receptionist must handle arbitrary user queries without pre-configuration.

5. **Claude Squad has no autonomous triage.** It requires a human to create workspaces and merge branches.

6. **Claude Flow is over-engineered for a 2-tier pattern.** 15-agent default, Byzantine consensus, graph attention mechanisms — these solve problems coding-vibe does not have (multi-contributor conflicts, large-team consensus, hierarchical negotiation).

7. **Git-isolated approaches (Claude Squad, Conductor) are slow for voice callbacks.** Merging branches and surfacing diffs takes seconds to minutes. A voice user expects callback in <60 seconds.

### 3.4 What coding-vibe Should Copy (5 Recommendations)

#### Recommendation 1 — Stateless worker pattern (from Anthropic Engineering)

Anthropic's research system treats sub-agents as **stateless workers**: each is spawned fresh for a subtask, returns a structured summary, and is discarded. No persistent identity, no session state carried over. Apply this to the CEO role in coding-vibe: each engineering task spawns a fresh engineer subprocess, gets a JSON result, and exits. No persistent engineer session state between tasks.

**Why:** Eliminates session-state bugs. A crashed engineer task has no stale state to corrupt. A fresh engineer is always available. Matches the voice call lifecycle: one task per call.

#### Recommendation 2 — Orchestrator's gap-analysis loop (from Anthropic Engineering + am-will/swarms)

Anthropic's orchestrator does not accept the first result blindly — it evaluates result quality and spawns follow-up agents if gaps remain. am-will/swarms has an explicit `verify` phase after the wave execution. For coding-vibe: the receptionist should not deliver results to the user until it has checked the CEO's output for completeness against the original requirements.

**Implementation:** After the CEO completes, the CS runs a short verification check (can be a lightweight LLM call or structured checklist) before delivering to the user. This is the "quality gate" step missing from the current coding-vibe loop.

#### Recommendation 3 — Claude Code's 4 spawn modes for the engineer role (from Claude Code native)

Claude Code's subagent spawn modes map directly to engineer subprocess types:

| Spawn Mode | Use in coding-vibe |
|---|---|
| `default` (in-process) | Lightweight engineer: same process, fast, for simple tasks |
| `fork` (child process) | Standard engineer: process isolation, fresh messages[] |
| `remote` (bridge/session) | Long-running engineer: persistent session via bridge |
| `in-process teammate` | Paired engineer: shared state, for collaborative review |

Use `fork` for the default CEO subprocess (isolation + clean state). Use `remote` for long-running tasks where session continuity matters (multi-turn refactoring).

#### Recommendation 4 — Claude Swarm's YAML role topology for the org architecture (from Claude Swarm)

Claude Swarm's YAML role/tool-scoping model is directly useful for the `coding-vibe` org architecture in OpenOPC:

```yaml
# Applied to coding-vibe org
roles:
  - id: receptionist
    role: cs-agent
    tools: [checkpoint, delegate, session_state]   # limited tool set
    mcp: [coding-vibe-mcp]
  - id: engineer
    role: ceo-engineer
    tools: [shell, file_ops, git, python_exec]     # full tool set
    execution: external  # spawn subprocess
```

Each role's tool scope is defined declaratively. The receptionist never gets `shell_exec` or `file_write`. The engineer always gets them. This is a security boundary as well as a functional one.

#### Recommendation 5 — Claude Code Agent Teams' shared task board for comms (from Claude Code Agent Teams)

The `TaskCreate`/`TaskUpdate` shared task board pattern from Claude Code Agent Teams is a better abstraction than the current flat delegation-file approach. Instead of:

```
~/.coding-vibe/delegation_<id>.json   (single file per task)
```

Adopt the task board pattern:

```
~/.coding-vibe/
├── task_board.json          # all tasks: id, status, assignee, result
├── inbox/cs/               # CS writes here
├── inbox/ceo/               # CEO writes here
├── tasks/<id>/              # per-task state: brief, result, checkpoints
└── completed/<id>/          # archived completed tasks
```

The task board file is a lightweight JSON state machine. Each task transitions: `pending → claimed → running → done → delivered`. The receptionist polls the board (or uses file watcher) — no need to scan a flat directory.

---

## Appendix A — Key URLs

| Project | Source |
|---|---|
| Claude Code Subagents | https://code.claude.com/docs/en/sub-agents |
| Claude Code Agent Teams | https://code.claude.com/docs/en/agent-teams |
| Claude Code Dynamic Workflows | https://code.claude.com/docs/en/workflows |
| Claude Code SDK Subagents | https://code.claude.com/docs/en/agent-sdk/subagents.md |
| Claude Code Multi-Agent Architecture | https://mintlify.com/sanbuphy/claude-code-source-code/llms.txt |
| Claude Swarm (parruda) | https://github.com/parruda/claude-swarm |
| Claude Squad (smtg-ai) | https://dev.to/arash/series/claude-squad |
| Claude Flow (ruvnet) | https://github.com/ruvnet/claude-flow |
| Claude Flow v3 Swarm | https://www.npmjs.com/package/@claude-flow/swarm |
| Conductor | https://github.com/runmymind/conductor (referenced in search results) |
| vibe-kanban | https://github.com/nobodyet/vibe-kanban, https://www.vibekanban.com/ |
| Anthropic Research Engineering Post | https://www.anthropic.com/engineering/how-we-built-our-multi-agent-research-system |
| am-will/swarms | https://github.com/am-will/swarms |
| Codex Parallel Orchestration (proposal) | https://github.com/openai/codex/discussions/22749 |
| OpenOPC (local prior art) | /Users/onezion12344/Projects/OpenOPC |

---

## PART 4 — Integrate-Once Abstraction: Does It Exist?

**Question restated:** Does any existing project give us ONE abstract orchestration/dispatch interface, with ALREADY-BUILT adapters for common harnesses — so we integrate that ONE framework and instantly support all harnesses, without writing per-harness glue ourselves?

For each project, answer four questions:
1. **Harness abstraction:** Does it abstract over MULTIPLE harness backends behind one interface?
2. **Provider/adapter layer:** Is there an explicit provider or adapter layer?
3. **Consumable by external receptionist:** Can it be consumed as library, MCP server, or plugin by an external orchestrator?
4. **Hook/injection control:** Does it support hook-based or injection-based control from an external process?

---

### 4.1 Integrate-Once Table: All Projects

| Project | (1) Multi-harness abstraction | (2) Provider/adapter layer | (3) Consumable by external receptionist | (4) Hook/injection control |
|---|---|---|---|---|
| **Claude Code Subagents** | ❌ Claude-only | ❌ No adapter layer — native spawn | ⚠️ SDK only (`claude-agent-sdk`); no MCP server | ✅ Hooks exist (`settings.json` hooks) |
| **Claude Code Agent Teams** | ❌ Claude-only | ❌ No adapter layer | ⚠️ SDK only; experimental | ⚠️ Hooks fire on task events |
| **Claude Code Dynamic Workflows** | ❌ Claude-only | ❌ No adapter layer | ❌ | ❌ |
| **Claude Swarm (parruda)** | ❌ Claude-only | ❌ No adapter layer | ⚠️ YAML-defined, MCP-based; can be driven externally | ⚠️ MCP message passing, but no hook |
| **Claude Squad (smtg-ai)** | ❌ Claude-only | ❌ No adapter layer | ❌ | ❌ |
| **Claude Flow (ruvnet)** | ❌ Claude-only (TypeScript agent pool) | ❌ No harness adapter layer — agents are generic | ⚠️ Message bus + FederationHub can be driven externally | ⚠️ No hook mechanism |
| **Conductor** | ⚠️ Claude Code + Codex only (2 harnesses) | ❌ No adapter layer — hardcoded per harness | ❌ Human-driven, no API | ❌ |
| **vibe-kanban** | ❌ Claude Code + Gemini + Codex + Amp (4 harnesses) | ⚠️ Per-harness config, not abstracted | ⚠️ Kanban board is the state store; no orchestration API | ⚠️ Board hooks, but no external process hook |
| **Anthropic Research** | ❌ Claude-only | ❌ No adapter layer | ❌ Internal research system only | ❌ |
| **am-will/swarms** | ❌ Claude Code + Codex only (2 harnesses) | ❌ No adapter layer — hardcoded CLI spawn | ⚠️ CLI-based; can be driven externally via filesystem | ❌ No hook |
| **Codex Cloud** | ❌ Codex-only | ❌ No adapter layer | ✅ REST API for task creation + polling | ❌ |
| **block/goose** | ❌ Block-internal only (single-agent CLI) | ❌ Model provider abstraction (Anthropic/OpenAI/Gemini), not coding-harness | ❌ CLI-only | ❌ No hook mechanism |
| **RooCode / Cline** | ❌ Claude-only (RooCode) / Claude-only (Cline) | ⚠️ Cline SDK (`@cline/sdk`) abstracts the agent runtime; no coding-harness adapter layer | ✅ Cline SDK is a TypeScript library; Cline Kanban is a web-based multi-agent board | ❌ No external process hook; TUI/IDE-driven |
| **mcp-agent (lastmile-ai)** | ⚠️ LLM abstraction (OpenAI/Anthropic/Google/Azure/Bedrock via MCP servers) | ✅ Full MCP adapter layer — tools, resources, prompts, OAuth | ✅ Python library + MCP server; durable via Temporal | ⚠️ MCP notification hooks (not external process injection) |
| **fast-agent (evalstate)** | ⚠️ LLM abstraction (Anthropic/OpenAI/Google/DeepSeek/Ollama) | ✅ MCP client + ACP + A2A adapter layer; HarnessMCPAdapter bridges MCP ↔ agents | ✅ Python library + `fast-agent serve` (MCP/ACP/A2A server); Harness API | ⚠️ Agent skills + hooks within framework; no external process hook |
| **OpenRouter / LiteLLM** | ✅ LLM model abstraction (1000+ models) | ✅ LiteLLM proxy = OpenAI-compatible API for all providers | ✅ LiteLLM is an HTTP proxy; can be consumed by any receptionist | ❌ No hook mechanism; pure proxy |
| **OpenRouter + agent-cli-to-api** (leeguooooo) | ✅ Claude Code / Codex / Cursor / Gemini CLIs all behind one `/v1` API | ✅ CLI adapter layer — wraps each CLI's stdout into OpenAI-compatible JSON response | ✅ HTTP API; any receptionist can POST tasks and poll for results | ❌ No hook mechanism; polling-based |
| **claude-anyteam** (JonathanRosado) | ✅ Claude Code as team lead; Codex/Gemini/Kimi as teammates | ✅ Adapter layer: non-Claude harnesses register as teammates | ⚠️ Claude Code plugin/team extension | ⚠️ Claude Code tool injection; no external process hook |
| **open-multi-agent** (open-multi-agent) | ⚠️ ACP-based; LLM planner + external coding agent + LLM reviewer | ✅ ACP adapter for external coding agent | ⚠️ Python library; ACP client drives it | ❌ No hook |
| **claude-Fulcrum** | ❌ Claude-only (26 agents, unified memory) | ❌ No harness adapter layer | ❌ Claude Code extension | ❌ |
| **openclaw** | ✅ Claude Code / Cursor / Copilot / OpenCode / Gemini via ACP plugin | ✅ ACP backend plugin layer | ⚠️ ACP-based; external process via ACP client | ❌ No hook |
| **Agent Maestro** (Joouis) | ⚠️ Claude Code / Codex / Cursor / Gemini via VS Code extension | ✅ Extension abstraction layer; exposes OpenAI/Anthropic/Gemini-compatible REST API | ✅ REST API + SSE; up to 20 concurrent tasks | ❌ No external process hook; VS Code extension-driven |
| **IDE Agent Kit** (ThinkOffApp) | ✅ Claude Code / GPT / Gemini / Kimi / Qwen | ✅ Webhook relay + tmux-based agent runners | ✅ REST webhook + room polling; external orchestrators can steer agents | ⚠️ Webhook injection into running sessions (closest to hook pattern) |
| **OpenOPC ExternalAgentAdapter** | ✅ claude_code / codex / cursor / opencode (4 backends; Gemini and Aider missing) | ✅ `ExternalAgentAdapter(ABC)` + `AdapterRegistry` — registry pattern, `get()`, `get_preferred()`, `get_ordered_available()` | ✅ Library (`opc exec`, `opc/engine.py`); can be called from external Python process | ⚠️ Hook-driven cross-layer propagation via `phase_transition_hook`; comms via `.opc-comms/` file mailbox |

---

### 4.2 New Candidate Details

#### agent-cli-to-api (leeguooooo) — "LiteLLM for agent CLIs"

The closest direct match to the "integrate-once" question. Wraps Claude Code, Codex, Cursor, and Gemini CLIs behind an OpenAI-compatible `/v1/chat/completions` API. A receptionist POSTs a task to `/v1/chat/completions` with `model: "claude-code"` or `model: "codex"` and gets back a streaming or final response — identical shape to an OpenAI API call.

**What it does well:** One interface, four harnesses. No per-harness glue in the receptionist.
**Gap:** CLI-only abstraction. No structured result envelope (task lifecycle, checkpoints, completion callbacks). No hook or callback mechanism — the receptionist must poll or stream-parse.
**Source:** GitHub `leeguooooo/agent-cli-to-api` (from prior research session).

#### open-multi-agent (open-multi-agent/open-multi-agent)

An ACP-based orchestrator that matches the coding-vibe shape exactly: an LLM planner decomposes the task, an external coding agent executes, and an LLM reviewer checks the result. Uses the Agent Client Protocol (ACP) to talk to the coding agent.

**What it does well:** Same 3-role topology as coding-vibe (planner → coder → reviewer). ACP is a real, standardized protocol.
**Gap:** Only one external coding agent backend (via ACP). The planner and reviewer are LLM calls, not separate harness instances. No voice-native path.
**Source:** GitHub `open-multi-agent/open-multi-agent` (from prior research session).

#### OpenOPC ExternalAgentAdapter (local)

OpenOPC already has the adapter layer that nobody else in the list fully matches:
- `ExternalAgentAdapter(ABC)` in `opc/layer3_agent/adapters/base.py` — abstract base defining `agent_type`, `default_command`, `configured_command()`, `resolve_binary()`, `is_new_session()`, `build_common_args()`
- `AdapterRegistry` in `opc/layer3_agent/adapters/registry.py` — `ADAPTER_CLASSES = {claude_code, cursor, codex, opencode}`, methods: `get()`, `get_preferred()`, `get_ordered_available()`
- `ExternalAgentBroker` in `opc/layer3_agent/external_broker.py` — coordinates approval, execution mode, session persistence

This is a **real adapter layer** — adding a new harness backend means writing one new `ExternalAgentAdapter` subclass and registering it. The receptionist (coding-vibe's CS role) calls `AdapterRegistry.get_preferred()` and never needs to know which CLI is running.

**Gaps:**
- **Gemini CLI missing** — no `ExternalAgentAdapter` for `gemini`.
- **Aider missing** — no adapter for `aider`.
- **Receptionist integration is file-based** (`.opc-comms/` mailbox), not a library call from an external process. coding-vibe currently shells out to `opc exec` as a subprocess; there is no Python API surface documented for an external caller.
- **No hook/injection mechanism** for an external process to steer a running OpenOPC instance. Phase hooks are internal to OpenOPC; there is no documented external hook entry point.

---

### 4.3 Verdict: Integrate-Once Abstraction — Does It Exist?

**Short answer: No project fully delivers "integrate once, support all harnesses."** But three projects are close enough to be actionable.

#### Best candidate: agent-cli-to-api (leeguooooo)

**Verdict: Closest to what we want, but incomplete.**

If we adopt `agent-cli-to-api`:
- ✅ We get ONE OpenAI-compatible HTTP interface for Claude Code, Codex, Cursor, and Gemini.
- ✅ No per-harness glue needed — add a new harness, it's behind the same `/v1` endpoint.
- ✅ Any receptionist (Python, TypeScript, any language) can consume it.
- ❌ No structured task lifecycle — just streaming/final text responses.
- ❌ No completion callbacks, no checkpoints, no delegation-file handshake.
- ❌ No hook mechanism for an external process to inject state into a running agent.

The coding-vibe receptionist would still need to implement the CS→CEO handshake (delegation file, claim, complete) on top of it. The abstraction solves the "spawn and get a result" problem; it does not solve the "coordinate a multi-turn CS→CEO loop" problem.

#### Runner-up: OpenOPC's ExternalAgentAdapter + coding-vibe MCP layer

**Verdict: Best architecturally, needs a thin Python API bridge.**

OpenOPC already has the multi-harness adapter layer we need. coding-vibe already has the MCP tooling for the CS→CEO handshake. The missing piece is a thin Python API so an external process (the voice bridge / receptionist) can call OpenOPC programmatically rather than via `subprocess.Popen(['opc', 'exec', ...])`.

If we add:
1. `ExternalAgentAdapter` for `gemini` and `aider` (2 new adapter subclasses)
2. A lightweight Python client: `opc.Client.run_task(task, role="engineer") → AsyncIterator[result_chunk]`
3. A file-watcher hook on `.opc-comms/` so the receptionist picks up delegation events without polling

Then OpenOPC IS the integrate-once abstraction. The receptionist calls one Python API; OpenOPC dispatches to whichever harness is configured for the engineer role.

#### What we build if neither is sufficient: thin adapter interface sketch

If existing projects are not adopted, the thin adapter interface looks like this:

```python
class CodingHarness(Protocol):
    """One interface, multiple backends."""
    agent_type: str                          # "claude_code" | "codex" | "cursor" | "gemini" | "aider"

    def spawn(self, task: str, context: dict) -> str:
        """Start a new engineer task. Returns task_id."""
        ...

    def stream(self, task_id: str) -> AsyncIterator[StatusEvent]:
        """Yield status updates: thinking / editing / running_tests / done."""
        ...

    def result(self, task_id: str) -> TaskResult:
        """Return structured result: summary, files_changed, exit_code."""
        ...

    def cancel(self, task_id: str) -> None:
        """Cancel a running task."""
        ...

class StatusEvent(NamedTuple):
    task_id: str
    phase: Literal["thinking", "editing", "running_tests", "done", "error"]
    message: str
    timestamp: float

class TaskResult(NamedTuple):
    task_id: str
    summary: str
    files_changed: list[str]
    exit_code: int
    raw_output: str
```

Each harness adapter implements `spawn() / stream() / result() / cancel()` by wrapping the appropriate CLI or SDK:
- `claude_code` adapter: `claude -p --output-format stream-json` + JSON parsing
- `codex` adapter: `codex exec --json` + JSONL parsing
- `cursor` adapter: `cursor agent -p --force` + stdout parsing
- `gemini` adapter: `gemini -p --output-format stream-json` + JSON parsing
- `aider` adapter: `aider --message --yes --no-stream` + `git diff` for files_changed

The receptionist never touches a CLI directly. It calls `harness.spawn(task)` and reads `harness.stream(task_id)`. Adding a new harness = one new adapter class. No changes to the receptionist.

**Effort estimate for this thin adapter layer: 3–5 days** (5 harness adapters, each ~100–150 LOC; streaming JSON parsing; task result normalization; error handling).

---

### 4.4 OpenOPC Assessed Through the Integrate-Once Lens

**Could OpenOPC BE that abstraction?**

| Factor | Verdict |
|---|---|
| Multi-harness abstraction | ✅ Yes — `ExternalAgentAdapter` ABC + `AdapterRegistry` covers 4 backends |
| Provider/adapter layer | ✅ Yes — registry pattern, `get_preferred()`, `get_ordered_available()` |
| Consumable by external receptionist | ⚠️ Partial — `opc exec` subprocess works today; no documented Python API for an external caller |
| Hook/injection control | ⚠️ Partial — internal `phase_transition_hook` exists; no documented external process hook |
| Coding-vibe org already configured | ✅ Yes — boss→architect→builder→reviewer chain in `.opc/config/company_orgs/` |
| Voice-ready | ❌ Not designed for sub-500ms voice triage — dispatcher loop is asyncio-based with wake events |

**What OpenOPC needs to be the integrate-once abstraction:**

1. **Python client API** — expose `opc.engine.run_company_task(org, task)` as a callable Python function, not just a CLI subprocess. Currently the only entry point is `subprocess.Popen(['opc', 'exec', ...])`. A 50-line thin wrapper that calls `opc/engine.py` directly would unlock this.

2. **Gemini + Aider adapters** — add two more `ExternalAgentAdapter` subclasses. Pattern is well-established from the existing 4.

3. **External hook entry point** — document a file-based or socket-based hook so the voice receptionist can inject a "new task arrived" event into a running OpenOPC instance without polling. The `.opc-comms/` file mailbox already exists; the receptionist just needs to write to it.

4. **Async result stream** — currently OpenOPC returns results after full execution. A `stream()` method wrapping the dispatcher loop with an asyncio queue would let the receptionist yield progress events in real time.

**If those four additions are made, OpenOPC becomes the integrate-once abstraction** — the receptionist calls one Python API, OpenOPC dispatches to whichever harness the engineer role is configured for, and the `.opc-comms/` mailbox handles the CS→CEO handshake. No per-harness glue in the receptionist. New harness = new adapter class. No changes to receptionist code.
