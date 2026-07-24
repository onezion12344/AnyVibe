# Qoder Agent SDK — Persistent Multi-Agent "Company" Pattern Research

> Research date: 2026-07-25
> Purpose: Determine if Qoder Agent SDK can implement a persistent, multi-agent orchestration pattern (like OpenOPC), or whether OpenOPC is the fallback.

---

## 1. Persistent / Resumable Sessions

**Verdict: YES — fully supported**

The Qoder Agent SDK provides two APIs with persistent session support:

### `QoderSDKClient` (class-based, long-lived)
```python
from qoder_agent_sdk import QoderSDKClient, QoderAgentOptions, access_token_from_env

options = QoderAgentOptions(auth=access_token_from_env())
async with QoderSDKClient(options=options) as client:
    await client.query("What's the capital of France?")
    async for msg in client.receive_response():
        ...

    # Inject new input into the same persistent session
    await client.query("What's the population of that city?")
    async for msg in client.receive_response():
        ...
```

Key methods for persistence:
- `client.query(prompt)` — send new turn; appends to same session
- `client.receive_response()` — consume until terminal `ResultMessage`
- `client.interrupt()` — interrupt without disconnecting
- `client.connect(prompt)` / `client.disconnect()` — manual lifecycle
- `client.set_model(model)` — switch model at runtime

### Session Control (resume / fork / continue)
Both `query()` and `QoderSDKClient` accept:
| Field | Behavior |
|---|---|
| `sessionId` | Creates session with this UUID |
| `resume: "session-id"` | Resumes a historical session by ID |
| `continue: true` | Resumes most-recently-modified session |
| `forkSession: true` | Forks a new session from an existing one |

```python
# Resume a named session
q = query({
    prompt: "Continue the prior conversation",
    options: { auth: access_token_from_env(), resume: "previous-session-id" },
})

# Fork from a session
q = query({
    prompt: "Explore a different direction",
    options: { auth: access_token_from_env(), resume: "source-id", forkSession: true },
})
```

This means the SDK supports true long-lived session state — you keep a session alive and keep injecting into it, exactly matching the owner's requirement.

---

## 2. Multi-Agent / Sub-Agent Orchestration

**Verdict: YES — two mechanisms, one of which is purpose-built for the "company" pattern**

### Mechanism A: SDK-level subagents (Python SDK)
Defined via `QoderAgentOptions.agents` dict of `AgentDefinition` objects:

```python
from qoder_agent_sdk import QoderAgentOptions, AgentDefinition, query

options = QoderAgentOptions(
    allowed_tools=["Agent"],  # Agent tool must be pre-authorized
    agents={
        "code-reviewer": AgentDefinition(
            description="Reviews code for correctness, security, maintainability.",
            prompt="""You are a code review specialist.
Review requested code and report concrete findings.
Sort by severity and include file paths.""",
            tools=["Read", "Grep", "Glob"],
            maxTurns=8,
        ),
        "test-executor": AgentDefinition(
            description="Runs tests and analyzes failures.",
            prompt="You are a test execution specialist...",
            tools=["Bash"],
        ),
    },
)

async for message in query(
    prompt="Use the code-reviewer agent to review auth.py",
    options=options,
):
    print(message)
```

Built-in subagents: `general-purpose`, `Explore`, `Plan`
Custom subagents: Any role with custom `prompt` (system prompt), `tools`, `disallowedTools`, `model`, `maxTurns`, `effort`, `permissionMode`, `skills`, `mcpServers`.

Delegation happens through the built-in `Agent` tool — the main session's `allowed_tools` must include `"Agent"`.

### Mechanism B: Managed Agents / Coordinator (Cloud API, more powerful)
The cloud API `multiagent` field creates a **coordinator pattern** — a persistent coordinator agent spawns child threads bound to other agents:

```json
POST /api/v1/cloud/agents
{
  "name": "task-coordinator",
  "model": "ultimate",
  "system": "You are a task coordinator responsible for delegating tasks to sub-agents.",
  "multiagent": {
    "type": "coordinator",
    "agents": [
      {"type": "agent", "id": "agent_019f...", "name": "Research Agent"},
      {"type": "agent", "id": "agent_019f...", "name": "Reviewer"},
      {"type": "self"}
    ]
  }
}
```

Coordinator auto-injects control tools:
- `create_agent(agent_id, agent_name, task)` — async, returns thread ID immediately
- `Agent(agent_id, prompt)` — synchronous/delegation, blocks until child completes
- `send_to_agent(thread_id, message)` — follow-up message to existing child
- `list_agents()` — list child threads and statuses

Child threads report via `send_to_parent(message)`.

Session lifecycle: coordinator creates session → delegates to children via `Agent` tool → children call `send_to_parent` → coordinator receives and continues.

**This is the closest match to OpenOPC's persistent-company pattern in the Qoder ecosystem.**

---

## 3. Custom Agents with Role System Prompts

**Verdict: YES — fully supported in both mechanisms**

**SDK-level (`AgentDefinition`):**
```python
AgentDefinition(
    description="...",       # routing description for the LLM
    prompt="...",             # role/system prompt — free-form text
    tools=["Read", "Grep"],   # tool allowlist
    disallowedTools=["Bash"], # tool blocklist
    model="auto",             # per-agent model override
    maxTurns=8,               # turn limit
    effort="high",            # reasoning effort
    permissionMode="default", # permission mode
    skills=["review"],        # preloaded skills
    mcpServers=["orders"],    # MCP server restrictions
    initialPrompt="...",      # auto-input when agent becomes main session role
)
```

**Cloud API (multiagent):** Each agent in the `agents` roster has its own `system` prompt defined at creation time. The coordinator never directly controls child prompts — they're baked into the agent snapshot.

---

## 4. Tools / MCP / Streaming / Language

| Aspect | Detail |
|---|---|
| **Languages** | Python (`qoder-agent-sdk` pip package, `anyio`-based async) and TypeScript (`@qoder-ai/qoder-agent-sdk` npm package) |
| **Auth** | Personal Access Token (PAT) via `QODER_PERSONAL_ACCESS_TOKEN` env var, or `qodercli_auth()` (reuse local CLI login) |
| **Tools** | Standard set: `Read`, `Write`, `Edit`, `Grep`, `Glob`, `Bash`, `Agent` (delegation) |
| **MCP** | `mcp_servers` field in `QoderAgentOptions`; `allowed_mcp_server_names` whitelist; `get_mcp_status()`, `set_mcp_servers()`, `reconnect_mcp_server()`, `toggle_mcp_server()` at runtime |
| **Streaming** | Both `query()` and `QoderSDKClient.receive_response()` return `AsyncIterator[Message]`. Messages are `AssistantMessage` (with `TextBlock`/`ToolUseBlock`), `ResultMessage`, and `StreamEvent` fragments |
| **SDK version** | `qoder-agent-sdk v1.0.2` (Python), mirrors TypeScript SDK |
| **Install** | `pip install qoder-agent-sdk` / `npm install @qoder-ai/qoder-agent-sdk` |

---

## 5. Competition / Hackathon Track

**Public info found — Qoder organizes multiple hackathon tracks globally:**

### Alibaba Cloud x Qoder Hackathon Series
- **Singapore (Jul 22, 2026):** One-day build + 2-week post-event window. Must use Qoder (IDE/CLI/JetBrains plugin). Focus: Spec-Driven Workflow (write Spec → Quest Mode → autonomous build). Prize: USD 1,500/1,000/500.
- **Ho Chi Minh City (Jul 24, 2026):** FSI track — risk assessment, fraud detection, compliance, CX. USD 3,000+ prize pool.
- **Tokyo (Feb 27, 2026):** Enterprise automation track — factory operations, maintenance scheduling, knowledge management agents.

### Common judging criteria across tracks:
1. **Spec-Driven Workflow** — Write a clear Spec document first, then use Quest Mode to autonomously execute
2. **Quest Mode Orchestration** — Break complex projects into verifiable multi-step tasks
3. **Qoder IDE / CLI / JetBrains Plugin** — Must use Qoder as primary build environment
4. **Qwen Models** — Optional, via Qoder's built-in Qwen access
5. **Practical functionality** — Clear use case, working demo

**No evidence found of a specific "competition track" requiring Qoder SDK (Python/TypeScript) vs Qoder IDE as a mandatory entry criterion.** The hackathons require using Qoder as a build tool; using the Agent SDK in a programmatic/scripted way would demonstrate deeper integration and likely be scored favorably, but is not stated as a hard requirement.

---

## Verdict: Can Qoder SDK Build a Persistent-Company Pattern?

**YES — with caveats.**

The Qoder Agent SDK supports all four required capabilities:

| Requirement | Qoder SDK Support |
|---|---|
| Persistent / resumable sessions | YES — `QoderSDKClient` multi-turn + `resume`/`continue`/`forkSession` |
| Multi-agent orchestration | YES — `AgentDefinition` subagents + `Agent` tool (SDK); `multiagent` coordinator (Cloud API) |
| Custom per-agent system prompts / roles | YES — `AgentDefinition.prompt` field (SDK); `system` per agent roster (Cloud API) |
| Tools / MCP / streaming | YES — full tool allowlists, MCP server config, async streaming iterators |

**What's missing vs. OpenOPC for a true "company" feel:**
- The SDK pattern is **delegation per-task** (main agent calls `Agent` tool for sub-agents), not a continuously-active agent team where the orchestrator maintains a "board" state. This is architecturally similar to OpenOPC but requires explicit orchestration logic in the main agent's prompt.
- **Session persistence across restarts** requires managing session IDs manually (store `session_id` from `init` message, resume by ID). The SDK doesn't automatically checkpoint a "company state" file.
- The **Cloud Managed Agents** coordinator is purpose-built for this pattern (child threads, mailbox, `create_agent`/`send_to_agent`/`list_agents`), but requires the cloud API and a Qoder account, not just the SDK pip/npm package.

**Recommendation:** Qoder SDK CAN build the persistent-company pattern. Use `QoderSDKClient` for the persistent main session + `agents` dict for the role team. The orchestrator agent prompt should contain the team definition and routing logic. For production use, consider the Cloud Managed Agents API for the coordinator/child-thread lifecycle management.

**OpenOPC remains the fallback** if you need: (a) zero external API dependency, (b) full local control over agent state, or (c) if the competition specifically requires a particular SDK.

---

## Sources

| # | URL | What it covers |
|---|---|---|
| 1 | https://docs.qoder.com/en/cli/sdk/python/agents | Python SDK subagents: built-in + custom, `AgentDefinition`, `Agent` tool delegation |
| 2 | https://docs.qoder.com/cloud-agents/managed-agents | Cloud Managed Agents: coordinator, child threads, `create_agent`, `send_to_agent`, mailbox |
| 3 | https://docs.qoder.com/en/cli/sdk/python | Python SDK quick-start: `query()` vs `QoderSDKClient`, auth, multi-turn |
| 4 | https://docs.qoder.com/en/cli/sdk/python/multi-turn-conversation | Multi-turn session lifecycle, `interrupt()`, auto/manual disconnect |
| 5 | https://docs.qoder.com/en/cli/sdk/session-control | Session resume/fork/continue, `sessionId`, `resume`, `forkSession`, `continue` |
| 6 | https://docs.qoder.com/en/cli/sdk/python/references | Full `QoderAgentOptions` type reference, all fields |
| 7 | https://luma.com/92h6pyl1 | Alibaba Cloud x Qoder Hackathon Singapore 2026 — Spec-Driven + Quest Mode judging criteria |
| 8 | https://docs.qoder.com/user-guide/quest/spec-driven | Spec-Driven Workflow documentation |
| 9 | https://qoder.com/ | Qoder homepage — product overview |
| 10 | https://docs.qoder.com/llms.txt | Full docs index |
