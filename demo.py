#!/usr/bin/env python3
"""Coding Vibe Demo -- Simulates the full CS to CEO to OpenOPC flow.

Usage:
  python3 demo.py              # Interactive demo
  python3 demo.py --scripted   # Non-interactive scripted demo
  python3 demo.py --task "Add a /health endpoint"  # Single task
"""

import argparse
import json
import os
import subprocess
import sys
import time

STATE_DIR = os.path.expanduser("~/.coding-vibe")
MCP_SERVER = os.path.expanduser("~/Projects/coding-vibe/mcp/server.py")


class MCPClient:
    """Talks to the Coding Vibe MCP server via stdio."""

    def __init__(self):
        self.proc = subprocess.Popen(
            ["python3", MCP_SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "demo", "version": "1.0"}
        }, 0)
        self._read_response()  # consume init response

    def _rpc(self, method, params, req_id):
        msg = json.dumps({
            "jsonrpc": "2.0", "id": req_id,
            "method": method, "params": params
        }) + "\n"
        self.proc.stdin.write(msg)
        self.proc.stdin.flush()

    def _read_response(self):
        line = self.proc.stdout.readline()
        if line:
            resp = json.loads(line)
            if "result" in resp:
                r = resp["result"]
                if "content" in r:
                    for c in r["content"]:
                        if c.get("type") == "text":
                            return json.loads(c["text"])
                return r
        return None

    def checkpoint(self, milestone, message, progress_pct=None):
        args = {"milestone": milestone, "message": message}
        if progress_pct is not None:
            args["progress_pct"] = progress_pct
        self._rpc("tools/call", {
            "name": "coding_vibe_checkpoint", "arguments": args
        }, 1)
        time.sleep(0.1)
        return self._read_response()

    def delegate(self, task_id, description, repo_path,
                 priority="normal", files=None):
        args = {
            "task_id": task_id, "description": description,
            "repo_path": repo_path, "priority": priority
        }
        if files:
            args["files_to_modify"] = files
        self._rpc("tools/call", {
            "name": "coding_vibe_delegate_to_ceo", "arguments": args
        }, 2)
        time.sleep(0.1)
        return self._read_response()

    def session_state(self):
        self._rpc("tools/call", {
            "name": "coding_vibe_session_state", "arguments": {}
        }, 3)
        time.sleep(0.1)
        return self._read_response()

    def claim_delegation(self, task_id="auto"):
        self._rpc("tools/call", {
            "name": "coding_vibe_claim_delegation",
            "arguments": {"task_id": task_id}
        }, 4)
        time.sleep(0.1)
        return self._read_response()

    def complete_delegation(self, task_id, summary, files_changed=None):
        args = {"task_id": task_id, "summary": summary}
        if files_changed:
            args["files_changed"] = files_changed
        self._rpc("tools/call", {
            "name": "coding_vibe_complete_delegation",
            "arguments": args
        }, 5)
        time.sleep(0.1)
        return self._read_response()

    def close(self):
        self.proc.terminate()


def simulate_ceo_via_mcp(client):
    """Simulate the CEO role using the actual MCP tools.

    This is the real CEO loop: claim → execute → complete.
    In production, the hook toggles to CEO protocol and the model does this.
    Here we simulate it to prove the MCP bridge works end-to-end.
    """
    print()
    print("=" * 60)
    print("CEO MODEL PICKING UP (via claim_delegation)")
    print("=" * 60)

    # CEO calls claim_delegation("auto") to pick up oldest pending task
    claim_result = client.claim_delegation("auto")
    if claim_result.get("status") != "claimed":
        print("[CEO] No pending tasks to claim:", json.dumps(claim_result, indent=2))
        return None
    print("[CEO] Claimed task:", claim_result["task_id"])
    print("[CEO] Task:", claim_result["description"])
    print("[CEO] Repo:", claim_result["repo_path"])

    time.sleep(0.5)

    repo_path = claim_result["repo_path"]
    if os.path.exists(repo_path):
        files = os.listdir(repo_path)
        print("[CEO] Found %d files in repo" % len(files))

    print("\n[CEO] Implementing...")
    for step in [
        "Analyzing requirements...",
        "Planning implementation...",
        "Writing code...",
        "Running tests...",
    ]:
        time.sleep(0.4)
        print("  ", step)

    # CEO completes the delegation — this auto-creates task-complete checkpoint
    summary = "Successfully implemented: " + claim_result["description"]
    result = client.complete_delegation(
        claim_result["task_id"],
        summary,
        files_changed=["main.py"],
    )
    print("\n[CEO] Delegation completed:", json.dumps(result, indent=2))
    return result


def demo_scripted():
    """Non-interactive scripted demo — full CS→CEO→CS loop via MCP."""
    client = MCPClient()
    repo = os.path.expanduser("~/Projects/OpenOPC_workplace/demo")
    task = "Add a /health endpoint returning status and uptime JSON"

    print("=" * 55)
    print("  CODING VIBE — Full Loop Demo (CS → CEO → CS)")
    print("=" * 55)
    print()

    # === TURN 1: CS Protocol ===
    print("--- Turn 1: CS gathers requirements ---")
    print('[CS]  "Coding Vibe, how can I help?"')
    print('[User] "Hey, I need to add a /health endpoint"')
    print()

    r = client.checkpoint(
        "requirements-gathered",
        "User needs /health endpoint in " + repo, 10)
    print("[CS] Checkpoint:", r["checkpoint"])

    r = client.delegate(
        "add-health-endpoint",
        "Add GET /health endpoint returning status + uptime JSON to the demo FastAPI server", repo)
    print("[CS] Delegated:", r["task_id"])
    print("[CS] Delegation file written:", r["delegation_file"])

    r = client.checkpoint(
        "delegating-to-ceo",
        "Task handed off to CEO. Will notify when done.", 30)
    print("[CS] Checkpoint:", r["checkpoint"])
    print('[CS]  "The team is on it! Go enjoy your ride."')
    print()
    print(">>> Hook detects pending delegation → next turn = CEO protocol")
    print()

    time.sleep(0.5)

    # === TURN 2: CEO Protocol ===
    print("--- Turn 2: CEO picks up and implements ---")
    result = simulate_ceo_via_mcp(client)
    if not result:
        print("[CEO] No tasks to process")
        return

    print()
    print(">>> Hook detects task-complete checkpoint → next turn = CS protocol")
    print()

    time.sleep(0.5)

    # === TURN 3: CS delivers ===
    print("--- Turn 3: CS delivers results ---")
    state = client.session_state()
    checkpoints = state.get("checkpoints", [])
    latest = checkpoints[-1] if checkpoints else {}

    print('[User] "How did it go?"')
    print('[CS]  "Good news! The engineering team finished."')
    print('[CS]  "' + latest.get("message", "Task complete!") + '"')
    print()
    print("   Progress: %d%%" % latest.get("progress_pct", 100))
    print("   Total checkpoints:", len(checkpoints))
    print("   Delegations:", len(state.get("delegations", [])))
    print("   State saved: %s/session.json" % STATE_DIR)
    client.close()
    print()
    print("Full loop complete! CS → CEO → CS, all via MCP bridge.")


def demo_interactive():
    """Interactive demo."""
    print("=" * 55)
    print("  CODING VIBE -- Interactive Demo")
    print("  Voice-First AI Coding Companion")
    print("  AdventureX 2026")
    print("=" * 55)
    print()
    print("You are on the go (cycling, walking, gym).")
    print("Call Coding Vibe to handle a coding task.")
    print()

    client = MCPClient()

    input("[Press Enter to start the call...] ")
    print()
    print("PHONE: [ring... ring...]")
    print('CS:    "Coding Vibe, how can I help you today?"')
    time.sleep(0.5)

    user_task = input('\nYOU:   "Hey, I need you to..." > ')
    if not user_task:
        user_task = "Add a /health endpoint to my demo FastAPI server"

    repo = input(
        'Which project? [~/Projects/OpenOPC_workplace/demo] > '
    ) or os.path.expanduser("~/Projects/OpenOPC_workplace/demo")
    priority = input("Priority? [normal] > ") or "normal"

    print()
    print('CS: "Got it. Let me summarize and delegate to our team."')

    task_id = user_task.lower().replace(" ", "-")[:40]

    r = client.checkpoint(
        "requirements-gathered",
        "User wants: " + user_task + " in " + repo, 10)
    print("   Checkpoint recorded:", r["checkpoint"])

    r = client.delegate(task_id, user_task, repo, priority)
    print("   Delegated to CEO:", r["task_id"])

    r = client.checkpoint(
        "delegating-to-ceo",
        "Task handed off to CEO. Will notify when done.", 30)
    print("   Checkpoint:", r["checkpoint"])

    print()
    print('CS: "The team is on it. Go enjoy your ride!"')

    input("\n[Press Enter to see CEO work in background...] ")

    result = simulate_ceo_via_mcp(client)

    input("\n[Press Enter to see CS deliver results...] ")

    state = client.session_state()
    checkpoints = state.get("checkpoints", [])
    latest = checkpoints[-1] if checkpoints else {}

    print()
    print('CS: "Good news! The engineering team finished."')
    print('CS: "' + latest.get("message", "Task complete!") + '"')
    print()
    print("   Progress: %d%% complete" % latest.get("progress_pct", 100))
    print("   Total checkpoints:", len(checkpoints))
    print("   Delegations:", len(state.get("delegations", [])))
    print()
    print("State saved: %s/session.json" % STATE_DIR)

    client.close()
    print("\nDemo complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coding Vibe Demo")
    parser.add_argument("--scripted", action="store_true")
    parser.add_argument("--task", type=str)
    args = parser.parse_args()

    try:
        if args.scripted:
            demo_scripted()
        elif args.task:
            client = MCPClient()
            repo = os.path.expanduser("~/Projects/OpenOPC_workplace/demo")
            task_id = args.task.lower().replace(" ", "-")[:40]
            print("Task:", args.task)
            r = client.checkpoint("start", args.task, 0)
            print("  Checkpoint:", r["checkpoint"])
            r = client.delegate(task_id, args.task, repo)
            print("  Delegated:", r["task_id"])
            print("  File:", r["delegation_file"])
            print("\n--- CEO Turn ---")
            simulate_ceo_via_mcp(client)
            print("\n--- CS Delivers ---")
            state = client.session_state()
            cp = state.get("checkpoints", [])
            print("  Latest:", cp[-1]["message"] if cp else "N/A")
            print("  Session: %d checkpoints, %d delegations" % (
                len(cp), len(state.get("delegations", []))))
            client.close()
        else:
            demo_interactive()
    except KeyboardInterrupt:
        print("\n\nDemo aborted.")
    finally:
        # Clean up state from demo
        sf = os.path.join(STATE_DIR, "session.json")
        if os.path.exists(sf):
            os.remove(sf)
        for f in os.listdir(STATE_DIR):
            if f.startswith("delegation_"):
                os.remove(os.path.join(STATE_DIR, f))
