"""
Coding Vibe MCP Server — Customer Service ↔ CEO Bridge.

A lightweight MCP server that acts as the checkpoint/reporting bridge between
a fast customer-service model and a powerful CEO reasoning model.

Architecture:
  User (voice) → Fast CS Model → [checkpoint] → MCP → User notified
                  ↓ (handoff via delegate_to_ceo)
                Delegation file written to ~/.coding-vibe/
                  ↓ (next turn)
                Hook detects pending delegation → injects CEO protocol
                  ↓
                SAME harness, CEO role → picks up delegation → executes
                  ↓ (complete_delegation)
                Hook detects completion → switches back to CS protocol
                  ↓
                CS model delivers results to user

Harness-agnostic: works with any MCP-compatible harness (Claude Code, Codex, Cursor, etc.)
"""

import json
import os
import time
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# --- State storage ---
STATE_DIR = Path(os.environ.get("CODING_VIBE_STATE_DIR", Path.home() / ".coding-vibe"))
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict[str, Any]:
    path = STATE_DIR / "session.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"checkpoints": [], "delegations": [], "created_at": time.time()}


def _save_state(state: dict[str, Any]) -> None:
    (STATE_DIR / "session.json").write_text(json.dumps(state, indent=2, ensure_ascii=False))


# --- MCP Server ---
server = Server("coding-vibe")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="coding_vibe_checkpoint",
            description=(
                "Report a progress checkpoint to the user. Call this at EVERY important milestone — "
                "after understanding the user's request, before starting work, when a sub-task completes, "
                "when results are ready. This keeps the user informed without them having to ask."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "milestone": {
                        "type": "string",
                        "description": "Short name of the milestone reached (e.g., 'requirements-gathered', 'code-generated', 'review-complete')",
                    },
                    "message": {
                        "type": "string",
                        "description": "Human-readable progress update to show the user. Be specific about what was done and what's next.",
                    },
                    "progress_pct": {
                        "type": "number",
                        "description": "Estimated completion percentage (0-100). Use 0 for 'just starting', 100 for 'all done'.",
                    },
                },
                "required": ["milestone", "message"],
            },
        ),
        Tool(
            name="coding_vibe_delegate_to_ceo",
            description=(
                "Delegate a complex reasoning/coding task to the CEO model. The CEO has access to "
                "a full engineering team (architect, builder, reviewer) via OpenOPC. "
                "Use this when the task requires deep reasoning, multi-file changes, or architectural decisions. "
                "Writes a delegation file that the CEO picks up on the next turn via the hook system."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Unique identifier for this delegation (e.g., 'add-auth-endpoint', 'fix-database-migration')",
                    },
                    "description": {
                        "type": "string",
                        "description": "Complete task description with requirements, constraints, and expected output. Be specific — the CEO needs full context.",
                    },
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the project repository the CEO should work in.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                        "description": "Priority level for the task.",
                    },
                    "files_to_modify": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific files that need to be changed or created.",
                    },
                },
                "required": ["task_id", "description", "repo_path"],
            },
        ),
        Tool(
            name="coding_vibe_session_state",
            description=(
                "Get the current session state — all checkpoints reported so far, pending delegations, "
                "and active CEO tasks. Use this to understand context before responding to the user."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="coding_vibe_claim_delegation",
            description=(
                "CEO: Claim a pending delegation and mark it as in-progress. "
                "Call this when you (as CEO) pick up a delegation to work on it. "
                "Returns the full delegation details including task description, repo path, and files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task_id of the pending delegation to claim. Use 'auto' to claim the oldest pending delegation.",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="coding_vibe_complete_delegation",
            description=(
                "CEO: Mark a delegation as completed. Call this when you finish the delegated task. "
                "This also records a checkpoint so the CS model can pick up your results and deliver them to the user. "
                "Include a summary the CS model can read verbatim to the user."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task_id of the delegation you completed.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "A summary of what was done — the CS model will relay this to the user. Include what changed, what was built, and any caveats.",
                    },
                    "files_changed": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files that were modified or created.",
                    },
                },
                "required": ["task_id", "summary"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    state = _load_state()

    if name == "coding_vibe_checkpoint":
        milestone = arguments["milestone"]
        message = arguments["message"]
        progress_pct = arguments.get("progress_pct", 50)

        checkpoint = {
            "milestone": milestone,
            "message": message,
            "progress_pct": progress_pct,
            "timestamp": time.time(),
        }
        state["checkpoints"].append(checkpoint)
        state["last_checkpoint"] = checkpoint
        _save_state(state)

        result = {
            "status": "recorded",
            "checkpoint": milestone,
            "total_checkpoints": len(state["checkpoints"]),
            "message_delivered": f"[Coding Vibe] {message}",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    elif name == "coding_vibe_delegate_to_ceo":
        delegation = {
            "task_id": arguments["task_id"],
            "description": arguments["description"],
            "repo_path": arguments["repo_path"],
            "priority": arguments.get("priority", "normal"),
            "files_to_modify": arguments.get("files_to_modify", []),
            "timestamp": time.time(),
            "status": "pending",
        }
        state["delegations"].append(delegation)
        _save_state(state)

        # Write delegation file for CEO pickup
        delegation_file = STATE_DIR / f"delegation_{arguments['task_id']}.json"
        delegation_file.write_text(json.dumps(delegation, indent=2, ensure_ascii=False))

        result = {
            "status": "delegated",
            "task_id": arguments["task_id"],
            "message": f"Task '{arguments['task_id']}' delegated to CEO. The CEO model will pick this up on the next turn.",
            "delegation_file": str(delegation_file),
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    elif name == "coding_vibe_claim_delegation":
        task_id = arguments["task_id"]

        # Find the delegation
        delegation = None
        for d in state["delegations"]:
            if task_id == "auto":
                if d["status"] == "pending":
                    delegation = d
                    break
            elif d["task_id"] == task_id:
                delegation = d
                break

        if not delegation:
            pending = [d["task_id"] for d in state["delegations"] if d["status"] == "pending"]
            return [TextContent(type="text", text=json.dumps({
                "status": "not_found",
                "task_id": task_id,
                "pending_tasks": pending,
            }, indent=2, ensure_ascii=False))]

        if delegation["status"] != "pending":
            return [TextContent(type="text", text=json.dumps({
                "status": "already_claimed",
                "task_id": delegation["task_id"],
                "current_status": delegation["status"],
            }, indent=2, ensure_ascii=False))]

        delegation["status"] = "in_progress"
        delegation["claimed_at"] = time.time()
        _save_state(state)

        # Update the delegation file
        delegation_file = STATE_DIR / f"delegation_{delegation['task_id']}.json"
        delegation_file.write_text(json.dumps(delegation, indent=2, ensure_ascii=False))

        return [TextContent(type="text", text=json.dumps({
            "status": "claimed",
            "task_id": delegation["task_id"],
            "description": delegation["description"],
            "repo_path": delegation["repo_path"],
            "priority": delegation["priority"],
            "files_to_modify": delegation["files_to_modify"],
            "message": "You have claimed this task. Execute it now. When done, call coding_vibe_complete_delegation.",
        }, indent=2, ensure_ascii=False))]

    elif name == "coding_vibe_complete_delegation":
        task_id = arguments["task_id"]
        summary = arguments["summary"]
        files_changed = arguments.get("files_changed", [])

        delegation = None
        for d in state["delegations"]:
            if d["task_id"] == task_id:
                delegation = d
                break

        if not delegation:
            return [TextContent(type="text", text=json.dumps({
                "status": "not_found",
                "task_id": task_id,
            }, indent=2, ensure_ascii=False))]

        delegation["status"] = "completed"
        delegation["completed_at"] = time.time()
        delegation["summary"] = summary
        delegation["files_changed"] = files_changed

        # Auto-create a task-complete checkpoint so CS can find it
        checkpoint = {
            "milestone": "task-complete",
            "message": summary,
            "progress_pct": 100,
            "task_id": task_id,
            "files_changed": files_changed,
            "timestamp": time.time(),
        }
        state["checkpoints"].append(checkpoint)
        state["last_checkpoint"] = checkpoint
        _save_state(state)

        # Update delegation file with final state
        delegation_file = STATE_DIR / f"delegation_{task_id}.json"
        delegation_file.write_text(json.dumps(delegation, indent=2, ensure_ascii=False))

        return [TextContent(type="text", text=json.dumps({
            "status": "completed",
            "task_id": task_id,
            "checkpoint_recorded": True,
            "message": "Task marked complete. The CS model will pick up your results on the next turn and deliver them to the user.",
        }, indent=2, ensure_ascii=False))]

    elif name == "coding_vibe_session_state":
        # Also list delegation files on disk (defense in depth)
        pending_files = sorted(
            str(p) for p in STATE_DIR.glob("delegation_*.json")
            if json.loads(p.read_text()).get("status") in ("pending", None)
        )
        state["pending_delegation_files"] = pending_files
        return [TextContent(type="text", text=json.dumps(state, indent=2, ensure_ascii=False))]

    else:
        raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
