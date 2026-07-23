# Plan: LiveKit Voice Pipeline for Coding Vibe

Replace the halfduplex stub in `voice_bridge.py` with a real-time voice pipeline
using LiveKit agents: Deepgram STT -> DeepSeek LLM (Boss) -> delegate_coding tool
-> OpenOPC chain -> Deepgram TTS.

## Global Constraints

- **Python 3.12+** with `uv` package manager (matching OpenOPC).
- **API keys from environment**: `DEEPSEEK_API_KEY`, `DEEPGRAM_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
- **DeepSeek as LLM** via OpenAI-compatible base URL `https://api.deepseek.com/v1`, model `deepseek-chat`.
- **Halfduplex must remain as fallback** — if LiveKit deps are missing or keys unset, fall back gracefully with a clear message.
- **The `delegate_coding` function_tool** calls OpenOPC via subprocess (`uv run opc exec`), streams JSON output, extracts the `final` event response, returns it to the LLM.
- **No new files unless necessary** — prefer extending `voice_bridge.py` in-place.
- **Reuse existing OpenOPC AudioChannel** `push_transcript()` for logging transcripts (non-blocking fire-and-forget).
- **Session management**: use the existing `coding-vibe-preset.py` to create task-backed sessions. The LiveKit agent creates a fresh session on startup.

## Tasks

### Task 1: Install dependencies and verify imports

**Consumes**: nothing (clean venv)
**Produces**: `requirements.txt` (or pyproject.toml), verified imports

Install livekit-agents with plugins. Verify all imports work. Create a `.env.example` file documenting required keys.

```bash
cd ~/Projects/coding-vibe
uv pip install livekit-agents python-dotenv
# Verify:
python3 -c "from livekit.agents import Agent, AgentSession, inference, cli; print('OK')"
```

Commit the dependency file and .env.example.

### Task 2: Create CodingVibeAgent class with delegate_coding tool

**Consumes**: Task 1 (installed deps), `~/Projects/OpenOPC/scripts/coding-vibe-preset.py` (session creation), `~/Projects/OpenOPC/.opc/projects/demo/` (company config)
**Produces**: `agent.py` — standalone module with `CodingVibeAgent` class

The agent class:
- Extends `livekit.agents.Agent`
- Instructions: "You are the Boss, CEO of Coding Vibe. You manage a software development company. When the user asks you to build something, delegate it to your engineering team using the delegate_coding tool. Keep responses concise and natural for voice — no markdown, no emojis. Speak directly."
- `@function_tool` named `delegate_coding(task: str) -> str`:
  1. Runs `coding-vibe-preset.py --project demo` to get a fresh session ID
  2. Calls `uv run opc exec -p demo --mode org --org coding-vibe --agent claude_code --session-id <ID> --stream-json "<task>"`
  3. Parses the streaming JSON output, collecting `message` events
  4. Returns the concatenated response text (or "Task delegated. The engineering team is working on it." if the result is in-progress)
- Clean subprocess handling: 120s timeout, capture stderr

### Task 3: Rewrite voice_bridge.py with `--mode livekit`

**Consumes**: Task 2 (`agent.py`), existing `voice_bridge.py` (halfduplex)
**Produces**: updated `voice_bridge.py` with `run_livekit()` function

Add `livekit` mode to the existing CLI:
- Keep `halfduplex`, `stepaudio`, `seeduplex` modes as-is
- Add `livekit` mode: imports `CodingVibeAgent` from `agent.py`, creates `AgentSession`, runs the LiveKit worker
- `run_livekit()` function:
  1. Load .env for API keys
  2. Create `AgentSession` with:
     - STT: `inference.STT("deepgram/nova-3", language="multi")`
     - LLM: `inference.LLM.with_openai(base_url="https://api.deepseek.com/v1", model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"])`
     - TTS: `inference.TTS("deepgram/aura-asteria-en")`
     - `TurnHandlingOptions` with interruption enabled
  3. Register `CodingVibeAgent` as the entrypoint
  4. Use `cli.run.app()` to start the worker
- Graceful fallback: if `LIVEKIT_URL` is not set, print "LiveKit not configured — set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET" and fall back to halfduplex
- Logging: use existing `[bridge]` prefix style

### Task 4: End-to-end smoke test

**Consumes**: Task 3 (full voice_bridge.py)
**Produces**: test script or manual test procedure verified

Verify the pipeline works end-to-end:
1. Start coding-vibe-demo FastAPI server on localhost:8000
2. Start voice_bridge.py in halfduplex mode (always works)
3. Push a transcript: "Boss: add a /status endpoint that returns the server uptime"
4. Verify OpenOPC chain executes (Architect plans → Builder implements → Reviewer checks)
5. Verify the response contains the implementation result
6. Curl the new endpoint to confirm it exists

If LiveKit keys are available, also test `--mode livekit`:
1. Start the LiveKit worker
2. Use LiveKit playground or CLI to connect
3. Speak a coding task
4. Verify voice response

Write results to `docs/superpowers/plans/test-results.md`.
