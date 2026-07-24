#!/usr/bin/env python3
"""End-to-end test: Receptionist.dispatch_async(backend="claude-code") on a real repo.

Runs a trivial, verifiable task through the real claude harness via the adapter,
using the async fire-and-callback flow. Prints status events as they stream and
the final result via the on_complete callback.

Usage:
  python3 e2e_test.py --backend claude-code --repo /tmp/cv-e2e
  python3 e2e_test.py --backend openopc --repo /tmp/cv-e2e --project demo
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from receptionist.core import Receptionist


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="claude-code")
    ap.add_argument("--repo", default="/tmp/cv-e2e")
    ap.add_argument("--project", default="demo")
    ap.add_argument(
        "--task",
        default="Create a file named hello.txt containing exactly the text HELLO_FROM_CODING_VIBE and nothing else.",
    )
    args = ap.parse_args()

    r = Receptionist()
    done = asyncio.Event()
    result_holder = {}

    def on_status(ev):
        print(f"  [status:{ev.kind}] {ev.text[:120]}")

    def on_complete(res):
        result_holder["result"] = res
        print("\n=== on_complete fired ===")
        print(f"  ok:            {res.ok}")
        print(f"  summary:       {res.summary[:300]}")
        print(f"  files_changed: {res.files_changed}")
        done.set()

    ctx = {"project": args.project} if args.backend == "openopc" else None

    print(f"[dispatch_async] backend={args.backend} repo={args.repo}")
    print(f"[task] {args.task}\n")

    handle = await r.dispatch_async(
        args.task,
        backend=args.backend,
        repo_path=args.repo,
        context=ctx,
        on_status=on_status,
        on_complete=on_complete,
    )
    print(f"[handle returned immediately] {handle}")
    print("[receptionist] 'The team is on it!' (non-blocking — waiting for callback)\n")

    try:
        await asyncio.wait_for(done.wait(), timeout=300)
    except asyncio.TimeoutError:
        print("!! timed out after 300s")
        return 2

    res = result_holder.get("result")
    return 0 if (res and res.ok) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
