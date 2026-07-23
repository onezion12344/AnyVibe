"""CodingVibeAgent — LiveKit voice agent that delegates coding work to OpenOPC.

The Boss (DeepSeek via LiveKit AgentSession) receives voice input, decides when to
delegate coding tasks, and calls the delegate_coding function_tool which shells out
to OpenOPC's Architect->Builder->Reviewer chain via Claude Code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path

from livekit.agents import Agent, RunContext
from livekit.agents.llm import function_tool

logger = logging.getLogger("coding-vibe-agent")

OPC_ROOT = Path.home() / "Projects" / "OpenOPC"


def _run_preset(project: str) -> str:
    """Run coding-vibe-preset.py and extract session_id from stdout."""
    import subprocess

    result = subprocess.run(
        ["uv", "run", "python3", "scripts/coding-vibe-preset.py", "--project", project],
        capture_output=True, text=True, timeout=30, cwd=str(OPC_ROOT),
    )
    output = result.stdout + result.stderr
    match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", output)
    if not match:
        raise RuntimeError(f"Failed to extract session_id from preset output:\n{output}")
    return match.group(0)


async def _exec_opc(session_id: str, task: str, project: str = "demo") -> str:
    """Run opc exec and collect response from streaming JSON output."""
    import subprocess

    cmd = [
        "uv", "run", "opc", "exec",
        "-p", project,
        "--mode", "org",
        "--org", "coding-vibe",
        "--agent", "claude_code",
        "--session-id", session_id,
        "--stream-json",
        task,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(OPC_ROOT),
    )

    collected: list[str] = []

    async def _read_stream(stream, label):
        while True:
            line = await stream.readline()
            if not line:
                break
            try:
                data = json.loads(line.decode())
                typ = data.get("type", "")
                payload = data.get("payload", {})
                if typ in ("message", "final"):
                    content = payload.get("content") or payload.get("response", "")
                    if content:
                        collected.append(content)
                elif typ == "error":
                    collected.append(f"ERROR: {payload.get('error', str(payload))}")
            except json.JSONDecodeError:
                pass

    await asyncio.wait_for(
        asyncio.gather(_read_stream(proc.stdout, "stdout"), _read_stream(proc.stderr, "stderr")),
        timeout=120,
    )

    if collected:
        return "\n".join(collected)
    return "Task delegated. The engineering team is working on it."


class CodingVibeAgent(Agent):
    def __init__(self, project: str = "demo") -> None:
        self._project = project

        super().__init__(
            instructions=(
                "You are the Boss, CEO of Coding Vibe. You manage a software development "
                "company. When the user asks you to build or fix something in code, delegate "
                "it to your engineering team using the delegate_coding tool. "
                "Keep responses concise and natural for voice — no markdown, no emojis. "
                "Speak directly. If the user just wants to chat, respond conversationally. "
                "When delegating, tell the user you're handing it off to the team, then "
                "report back what they accomplished."
            ),
        )

    @function_tool
    async def delegate_coding(self, context: RunContext, task: str) -> str:
        """Delegate a coding or software development task to the engineering team.

        Use this when the user asks you to write code, fix bugs, add features,
        create endpoints, or any other software development work. The engineering
        team (Architect -> Builder -> Reviewer) will handle it.

        Args:
            task: A clear description of what needs to be built or fixed.
        """
        logger.info(f"Delegating coding task: {task[:100]}...")

        loop = asyncio.get_running_loop()
        session_id = await loop.run_in_executor(None, _run_preset, self._project)
        logger.info(f"Session: {session_id}")

        result = await _exec_opc(session_id, task, self._project)
        logger.info(f"Result: {result[:200]}...")
        return result
