# Voice AI Framework Research — Full-Duplex + Tool-Calling, Self-Hosted
**Date:** 2026-07-25  
**Use-case:** Drop-in API keys → full-duplex phone-call-style CS agent with tool-calling, self-hosted on Mac, web/browser client, bring-your-own STT/LLM/TTS (StepFun, Deepgram, DeepSeek, MiMo)

---

## 1. Framework Comparison Table

| Criterion | **Pipecat** ⭐ | **LiveKit Agents** | **TEN Framework** | **Vocode** | **Bolna** | **Ultravox** | **Vapi OSS** |
|---|---|---|---|---|---|---|---|
| **GitHub Stars** | 13,662 | 11,483 | 10,896 | 3,779 | 706 | 4,476 | N/A (hosted) |
| **License** | BSD-2-Clause | Apache 2.0 | NOASSERTION | MIT | MIT | MIT | Proprietary |
| **Full-duplex / Barge-in** | ✅ Yes (Silero VAD, interruption score 4.90/5 — best in benchmark) | ✅ Yes (built-in VAD, streaming) | ✅ Yes (RTC + WebSocket) | ✅ Yes | ✅ Yes | ✅ Yes (model-level) | ✅ Yes (hosted) |
| **Tool / Function-calling** | ✅ First-class (`FunctionSchema` / `ToolsSchema`) | ✅ First-class (sync + async + provider tools) | ✅ Yes | ✅ Yes | ✅ Yes | ⚠️ Model-level only | ⚠️ Hosted only |
| **BYO STT** | ✅ Deepgram, OpenAI, AssemblyAI, AWS, Azure, Google, Mistral, Moonshine, NVIDIA, Sarvam, Soniox, Speechmatics, Whisper, xAI + more | ✅ Deepgram, AssemblyAI, Azure, Google, OpenAI, Whisper | ✅ Extensible | ✅ Deepgram, OpenAI, Google, AssemblyAI | ✅ Deepgram | ❌ Ultravox *is* the STT | ❌ |
| **BYO LLM** | ✅ OpenAI, Anthropic, Groq, Mistral, Together, AWS Bedrock, xAI, Google, Azure + OpenAI-compatible (any base URL) | ✅ OpenAI, Anthropic, Groq, Google, xAI, Ollama, custom OpenAI-compatible | ✅ Extensible | ✅ OpenAI, Anthropic, Cohere, Groq, Llama | ✅ OpenAI, DeepSeek, Llama | ❌ Ultravox *is* the LLM | ❌ |
| **BYO TTS** | ✅ ElevenLabs, Cartesia, Deepgram, Google, Hume, Kokoro, LMNT, Mistral, Neuphonic, NVIDIA, OpenAI, Piper, Resemble, Rime, Sarvam, Smallest, Soniox, Speechmatics, Together, xAI, XTTS | ✅ ElevenLabs, Cartesia, Deepgram, Google, LMNT, OpenAI, Rime, ElevenLabs (partial) | ✅ Extensible | ✅ ElevenLabs, Cartesia, Azure, Google, Microsoft, Play.ht | ✅ Cartesia, ElevenLabs | ❌ Ultravox *is* the TTS | ❌ |
| **OpenAI-compatible LLM (e.g. StepFun / DeepSeek)** | ✅ Use `OpenAILLMService` with `base_url` override | ✅ Use `OpenAI` class with `base_url` override | ✅ via extension | ✅ Via OpenAI-compatible | ✅ DeepSeek listed | ❌ | ❌ |
| **Web / Browser client** | ✅ SmallWebRTCTransport (P2P, zero cloud), Daily, FastAPI WS, LiveKit, WhatsApp | ✅ Via LiveKit RTC room | ✅ RTC + WebSocket | ✅ Telephony, browser | ✅ Telephony | ⚠️ API-only | ✅ Browser SDK |
| **Self-host on Mac** | ✅ Pure Python, pip install, zero infra | ✅ Mac runs; needs LiveKit room server (can be local) | ✅ Pure Python/Go | ✅ Yes | ✅ Yes | ⚠️ Heavy (GPU recommended) | ❌ Hosted only |
| **Multilingual / Chinese** | ✅ Any Chinese-capable STT/LLM/TTS works | ✅ Yes | ✅ Yes (Chinese docs, contributors) | ✅ Yes | ✅ Yes (DeepSeek) | ⚠️ Model-limited | ✅ Yes |
| **Turn-taking quality** | ✅ Benchmark: interruption 4.90/5; latency ~3.15s (P50) | ✅ Benchmark: ~2.46s (P50), near Vapi | ⚠️ Benchmark data scarce | ✅ ~3.16s (P50) | ⚠️ Benchmark data scarce | ✅ Model-level latency ~1.6s | ✅ ~2.34s (P50) |
| **Maturity / Community** | Very high (280 contrib, 115 releases, active) | Very high (active, well-documented) | High (80 contrib, 117 releases, active) | Moderate (60 contrib, slow) | Low (40 contrib, maintainer needed) | Moderate (20 contrib) | High (commercial) |
| **Rust / C++ components** | No (pure Python) | Yes (C Rust components) | Yes (C/C++/Rust) | No (pure Python) | No (pure Python) | No (pure Python) | No |

**Sources:**  
- https://github.com/pipecat-ai/pipecat  
- https://github.com/livekit/agents  
- https://github.com/ten-framework/ten-framework  
- https://github.com/vocodedev/vocode-core  
- https://github.com/bolna-ai/bolna  
- https://github.com/fixie-ai/ultravox  
- https://benchmarks.cekura.ai/  
- https://docs.pipecat.ai/pipecat/learn/function-calling  
- https://docs.livekit.io/agents/logic/tools/  
- https://theten.ai/docs/ten_agent_examples/overview

---

## 2. Top Recommendation

> **Pipecat** is the best fit for "drop-in keys → full-duplex CS agent with tool-calling, self-hosted" on Mac.

### Why Pipecat over the others

**Against LiveKit Agents:** LiveKit is equally capable and arguably more polished, but it requires you to run or connect to a LiveKit room server even in local development — an extra process. Pipecat's `SmallWebRTCTransport` is pure P2P, no server required, which is strictly simpler on a Mac. Both have strong turn-taking quality.

**Against TEN Framework:** TEN has excellent multilingual/Chinese support (Simplified Chinese docs, large Chinese contributor base) and supports RTC + WebSocket. However its license is `NOASSERTION` (not explicitly permissive), it has a heavier multi-language build surface (C/C++/Rust/Go), and its Python API is less ergonomic than Pipecat's. Pipecat is the safer long-term bet for a Python-first team.

**Against Vocode:** Vocode is solid but has stalled — last push was November 2024, and the core repo has not kept pace with Pipecat or LiveKit. Its community is smaller and documentation less maintained.

**Against Bolna:** Bolna is clean conceptually (JSON config, orchestration platform), but the repo is actively seeking new maintainers and its community traction is thin (706 stars). Too risky for production.

**Against Ultravox:** Ultravox is an end-to-end model (STT+LLM+TTS fused), not a general framework. You cannot swap in StepFun or DeepSeek. Not suitable unless you want to use Ultravox's model exclusively.

**Against Vapi:** Vapi is a hosted service. It has an MCP server and browser SDK, but no meaningful open-source framework you can self-host.

### When TEN Framework might be better

If Chinese-first UX and native Chinese documentation are critical, TEN (10,896 stars, active Chinese contributor base, explicit Simplified/Japanese/Korean READMEs) is the stronger choice. The `NOASSERTION` license needs legal sign-off before production use.

---

## 3. How Tool-Calling / Dispatch-Hook Wires In (Pipecat)

Pipecat treats function-calling as a first-class pipeline step. Your "dispatch task to engineer" webhook is a plain Python function decorated with `@function_tool` (or registered via `FunctionSchema`), and Pipecat's LLM service will call it automatically when the LLM decides to.

### Architecture

```
Browser (WebRTC via SmallWebRTCTransport)
        │ audio frames
        ▼
STT (e.g. DeepgramRealtimeSTTService)
        │ text transcript
        ▼
LLMContextAggregator  →  determines turn end via SileroVAD
        │ context frame (user turn complete)
        ▼
LLM (e.g. OpenAILLMService with base_url=StepFun/DeepSeek)
        │ function_call frame (if tool needed)
        ▼
Your tool handler (Python function, calls your webhook)
        │ result text
        ▼
TTS (e.g. DeepgramTTSService / ElevenLabs / Cartesia)
        │ audio frames
        ▼
Browser (audio output)
```

### Tool definition example

```python
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import LLMRunFrame

# Define the tool schema
dispatch_task_schema = FunctionSchema(
    name="dispatch_task_to_engineer",
    description="Dispatch a new engineering task to the on-call engineer via webhook",
    properties={
        "task_title": {"type": "string", "description": "Brief title of the task"},
        "task_description": {"type": "string", "description": "Full description of what needs to be done"},
        "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"], "description": "Task priority level"},
    },
    required=["task_title", "task_description", "priority"],
)

async def handle_dispatch_task(task_title: str, task_description: str, priority: str) -> str:
    """Call the engineer dispatch webhook."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://your-hook.example.com/dispatch",
            json={"title": task_title, "desc": task_description, "priority": priority},
        )
    return f"Task dispatched. Status: {resp.status_code}"

# Register tool with LLM service
tools = ToolsSchema(standard_tools=[dispatch_task_schema])
llm = OpenAILLMService(
    api_key=os.getenv("OPENAI_API_KEY"),   # or StepFun / DeepSeek key
    base_url=os.getenv("OPENAI_BASE_URL"), # e.g. https://api.stepfun.com/v1
    model=os.getenv("LLM_MODEL", "step-2-16k"),
    tools=tools,
)
# hook the handler:
llm.register_function("dispatch_task_to_engineer", handle_dispatch_task)
```

When the LLM decides a task dispatch is needed, Pipecat automatically:
1. Pauses the audio pipeline
2. Calls your Python handler
3. Feeds the result back into the LLM context
4. Resumes the TTS pipeline with the LLM's response

No manual orchestration required.

---

## 4. Quickstart — Pipecat

### Install

```bash
# Using uv (recommended)
uv tool install "pipecat-ai[cli]"

# Or pip
pip install "pipecat-ai[web,websocket]"
```

### Minimal config (`.env`)

```bash
# LLM — bring your own, using StepFun as example
OPENAI_API_KEY=your_stepfun_key
OPENAI_BASE_URL=https://api.stepfun.com/v1
OPENAI_MODEL=step-2-16k

# STT — Deepgram
DEEPGRAM_API_KEY=your_deepgram_key

# TTS — Cartesia (or swap for ElevenLabs, Deepgram, etc.)
CARTESIA_API_KEY=your_cartesia_key
CARTESIA_VOICE_ID=71a7ad14-091c-4e8e-a314-022ece01c121
```

### Minimal bot (`bot.py`)

```python
import os
from dotenv import load_dotenv
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams
from pipecat.transports.small_webrtc import SmallWebRTCTransport
from pipecat.services.deepgram import DeepgramSTTService
from pipecat.services.openai import OpenAILLMService
from pipecat.services.cartesia import CartesiaTTSService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame

load_dotenv()

async def main(transport):
    # 1. STT
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    # 2. LLM with StepFun-compatible base URL
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),  # https://api.stepfun.com/v1
        model=os.getenv("OPENAI_MODEL"),
    )

    # 3. TTS
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        settings=CartesiaTTSService.Settings(
            voice=os.getenv("CARTESIA_VOICE_ID"),
        ),
    )

    # 4. VAD + context
    from pipecat.processors.aggregators.llm_response import (
        LLMUserResponseAggregator, LLMAssistantResponseAggregator,
    )
    context = LLMContext()
    user_aggregator = LLMUserResponseAggregator(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )
    assistant_aggregator = LLMAssistantResponseAggregator(context)

    # 5. Pipeline
    pipeline = Pipeline([
        transport.input(),
        stt,
        user_aggregator,
        llm,
        tts,
        transport.output(),
        assistant_aggregator,
    ])

    runner = PipelineRunner()
    runner.run(pipeline, PipelineParams(allow_interruptions=True))

# SmallWebRTCTransport — zero server, browser connects directly
transport = SmallWebRTCTransport()
# launch bot with: python bot.py  (opens browser page for audio I/O)
```

### Switching providers in 1 line

```python
# Swap LLM to DeepSeek
llm = OpenAILLMService(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    model="deepseek-chat",
)

# Swap TTS to Deepgram
from pipecat.services.deepgram import DeepgramTTSService
tts = DeepgramTTSService(api_key=os.getenv("DEEPGRAM_API_KEY"), voice="aura-2-arcas-en")
```

### Web/browser client

```html
<!-- small-webrtc provides a pre-built HTML client -->
<script src="https://unpkg.com/@pipecat-ai/small-webrtc@latest/dist/index.js"></script>
<script>
  const pc = new SmallWebRTCPeer({ transportUrl: "ws://localhost:7860" });
  pc.start(); // opens mic, connects to bot
</script>
```

---

## 5. Key Findings & Caveats

| Finding | Detail |
|---|---|
| **Interruption / barge-in benchmark** | Pipecat scores 4.90/5 — highest of all tested platforms; ElevenLabs fastest at 1.73s P50 but has very long P95 tail (max 10.4s) |
| **StepFun compatibility** | Use `OpenAILLMService` with `base_url="https://api.stepfun.com/v1"` — StepFun's API is OpenAI-compatible |
| **DeepSeek compatibility** | Same pattern, `base_url="https://api.deepseek.com/v1"` |
| **Mac self-host friction** | Zero for Pipecat with `SmallWebRTCTransport`. LiveKit requires a room server; TEN requires build toolchain |
| **TEN license** | `NOASSERTION` — confirm with legal before production use |
| **Bolna status** | "Actively looking for maintainers" — avoid for production |
| **Vapi** | Not open-source — only MCP server and hosted SDK available |
| **Ultravox** | An LLM model, not a framework — cannot swap providers |

---

## Sources

| URL | Notes |
|---|---|
| https://github.com/pipecat-ai/pipecat | Main repo (13,662 stars, BSD-2) |
| https://docs.pipecat.ai/pipecat/learn/function-calling | Function-calling docs |
| https://docs.pipecat.ai/pipecat/learn/transports | Transport options |
| https://docs.pipecat.ai/pipecat/learn/speech-to-text | STT providers list |
| https://github.com/livekit/agents | Main repo (11,483 stars, Apache-2.0) |
| https://docs.livekit.io/agents/logic/tools/ | Tool-calling docs |
| https://livekit.com/blog/build-your-first-ai-voice-agent-python | Getting started tutorial |
| https://github.com/ten-framework/ten-framework | Main repo (10,896 stars, NOASSERTION) |
| https://theten.ai/docs/ten_agent_examples/overview | Agent examples docs |
| https://github.com/vocodedev/vocode-core | Main repo (3,779 stars, MIT) |
| https://github.com/bolna-ai/bolna | Main repo (706 stars, MIT) |
| https://github.com/fixie-ai/ultravox | Main repo (4,476 stars, MIT) |
| https://benchmarks.cekura.ai/ | Independent turn-taking + interruption benchmarks |
| https://developers.deepgram.com/docs/pipecat-integration | Deepgram × Pipecat integration |
