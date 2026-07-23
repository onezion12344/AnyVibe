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

    def close(self):
        self.proc.terminate()


def simulate_ceo(description, repo_path, task_id):
    """Simulate what the CEO model does with a delegation."""
    print()
    print("=" * 60)
    print("CEO MODEL PICKING UP:", task_id)
    print("  Repo:", repo_path)
    print("  Task:", description)
    print("=" * 60)
    time.sleep(0.8)

    print("\n[CEO] Reading project context...")
    time.sleep(0.4)
    if os.path.exists(repo_path):
        files = os.listdir(repo_path)
        print("[CEO] Found %d files in repo" % len(files))

    print("\n[CEO] Reasoning about the task...")
    for step in [
        "Analyzing requirements and constraints...",
        "Designing the implementation approach...",
        "Planning Architect -> Builder -> Reviewer chain...",
    ]:
        time.sleep(0.5)
        print("  ", step)

    print("\n[CEO] Delegating to OpenOPC engineering team...")
    time.sleep(0.6)
    print("  -> Architect: Designing the solution...")
    time.sleep(0.4)
    print("  -> Builder: Implementing the code...")
    time.sleep(0.4)
    print("  -> Reviewer: Verifying the implementation...")
    time.sleep(0.4)

    result = {
        "task_id": task_id,
        "status": "completed",
        "summary": "Successfully implemented: " + description,
        "files_changed": ["main.py"],
        "tests_passed": True,
    }
    print("\n[CEO] Task complete:", json.dumps(result, indent=2))
    return result


def demo_scripted():
    """Non-interactive scripted demo."""
    client = MCPClient()
    repo = os.path.expanduser("~/Projects/OpenOPC_workplace/demo")
    task = "Add a /health endpoint returning status and uptime JSON"

    steps = [
        ("CS", "Call received. User wants to add a /health endpoint."),
        ("CP", client.checkpoint(
            "requirements-gathered",
            "User needs /health endpoint in demo server", 10)),
        ("DL", client.delegate(
            "add-health-endpoint",
            "Add GET /health endpoint returning status + uptime JSON", repo)),
        ("CP", client.checkpoint(
            "delegating-to-ceo",
            "Task delegated to CEO for implementation", 30)),
        ("CEO", "Reasoning + OpenOPC chain (Architect->Builder->Reviewer)..."),
        ("CP", client.checkpoint(
            "task-complete",
            "Added /health endpoint. Returns status + uptime. Tests pass.", 100)),
        ("CS", "Delivering results: Your /health endpoint is live!"),
    ]

    for label, content in steps:
        time.sleep(0.3)
        if isinstance(content, str):
            print("[%s] %s" % (label, content))
        else:
            print("[%s] %s" % (label, json.dumps(content)[:120]))

    state = client.session_state()
    print("\nSession: %d checkpoints, %d delegations" % (
        len(state.get("checkpoints", [])),
        len(state.get("delegations", []))))
    print("State saved to: %s/session.json" % STATE_DIR)
    client.close()


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

    result = simulate_ceo(user_task, repo, task_id)

    client.checkpoint(
        "task-complete",
        "Done! " + result["summary"] + ". Tests passed.", 100)

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
            state = client.session_state()
            print("  State: %d checkpoints, %d delegations" % (
                len(state.get("checkpoints", [])),
                len(state.get("delegations", []))))
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
