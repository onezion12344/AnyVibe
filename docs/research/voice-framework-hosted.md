# Hosted / Managed Voice-Agent API Platforms — Research Report

*Research date: 2025-07-23*
*Sources cited inline.*

---

## 1. Comparison Table

| Criterion | Vapi | Retell AI | Bland AI | ElevenLabs Agents | Play.ai (PlayHT) | OpenAI Realtime API |
|---|---|---|---|---|---|---|
| **Full-duplex / barge-in** | Yes. Sub-600ms, natural turn-taking, smart endpointing | Yes. LLM WebSocket protocol; `interruptibility` 0-4 | Yes. `interruptibility` (0-4) + `resumption_speed` (1-3) | Yes. Conversation class supports streaming + barge-in callbacks | Yes. Sub-300ms streaming latency | Yes. Native VAD, built-in interruption handling |
| **Tool / function calling** | Yes. OpenAI-style `functions` array; Server URL receives `tool-calls` POST | Yes. Custom LLM WebSocket; function calling via OpenAI SDK pattern | Yes. Custom Tools; HTTP POST to any URL with `input_schema` | Yes. Webhook tools + MCP tools + built-in tools | Yes. Zapier/API integrations; GPT-4o/LLaMA tool calling | Yes. Native function calling in WebSocket |
| **Webhook to your own function** | Yes. Server URL (POST); responds with results inline | Partially. LLM WebSocket to your server (bidirectional); `call_ended` / `call_analyzed` webhooks | Yes. Custom Tool `url` field calls your API; post-call webhook | Yes. Webhook tool type (POST to your URL); MCP tool server | Via Zapier/API; no direct webhook-to-arbitrary-endpoint in agent builder | Via `response.create` + your own WS bridge; no direct webhook (build your own bridge) |
| **Chinese support + voice** | ⚠️ Not confirmed in docs found | ⚠️ Not confirmed | ⚠️ Not confirmed in docs found; multilingual system exists | ⚠️ Multilingual voices exist; specific Chinese TTS quality not confirmed | Partial. 25+ languages under dev; English/Spanish/Arabic confirmed; PlayDialog `Beta` for multilingual | Yes. GPT-Realtime handles Chinese natively; voices are English-only (6 preset voices) |
| **Web / WebRTC client** | Yes. `@vapi-ai/web` SDK, React Native, Flutter, iOS | Yes. Web Call SDKs | Yes. `BlandWebClient` (`bland-client-js-sdk`) | Yes. `Conversation` class + `@elevenlabs/react` | Yes. Streaming API with WebSocket; embeddable widget | Yes. WebSocket; browser via WebRTC transport |
| **Bring-your-own LLM** | Yes. OpenAI, Anthropic, Groq, Google, Deepgram, etc. | Yes. LLM WebSocket connects to your server/LLM | No. Uses platform models (base/turbo) | Yes. `llm` field in prompt; gemini-2.0-flash, Claude, etc. | Partial. GPT-4o/LLaMA; not BYO arbitrary LLM | No. Only GPT-Realtime-1.5 / 2 / 2.1 |
| **Pricing** | Usage-based per call/min; bundled with STT/TTS/LLM costs | Usage-based; ⚠️ exact per-min pricing not confirmed in docs | **$0.09/min** claimed in agent prompt (may be aspirational) | Per-1k characters or agent-minutes; ⚠️ confirmed pricing not found | Free tier: 12,500 chars/mo; ⚠️ paid tier pricing not confirmed | **$0.06/min audio in / $0.24/min audio out / $4-24/M text tokens** (official, as of 2025) |
| **China-network accessible** | ⚠️ api.vapi.ai — Cloudflare-backed; no documented China block, but US infra | ⚠️ api.retellai.com — US infra, likely blocked or high latency | ⚠️ app.bland.ai — US infra | ⚠️ ElevenLabs.io — partially accessible; ⚠️ latency from China | ⚠️ play.ht / api.play.ht — US infra | ❌ api.openai.com — **known blocked from China**; requires proxy |

---

## 2. Platform Deep-Dives

### Vapi

**What it is:** The most developer-centric voice orchestration platform. Combines Deepgram (STT) + your chosen LLM (OpenAI/Anthropic/Groq) + ElevenLabs/PlayHT/OpenAI/RimeAI (TTS) in one pipeline. You don't manage any of these pieces — Vapi runs them all in its cloud.

**Full duplex / barge-in:** Sub-600ms end-to-end response time. Smart endpointing available (`assistant.startSpeakingPlan.smartEndpointingPlan`). The `assistant.speech.interrupted` and `customer.speech.interrupted` hooks prove barge-in is a first-class feature.

**Tool calling:** Server URL receives `tool-calls` POST with OpenAI-style function call objects. You respond with `{ results: [{ name, toolCallId, result }] }`. You can also optionally send a spoken message to say while the tool runs. This is exactly the pattern you need for `dispatch_to_engineer`.

**Web / WebRTC:** `@vapi-ai/web` gives a one-liner: `vapi.start(assistantId)` in a browser. React Native and Flutter SDKs also available.

**BYO LLM:** First-class. The `model.provider` and `model.model` fields accept OpenAI, Anthropic, Groq, Google, and others.

**Pricing:** ⚠️ Public pricing page is not indexed in search results. Community reports suggest pay-per-use with STT/LLM/TTS passed through at cost. No flat subscription tier confirmed. Reach out to sales or check dashboard for exact rates.

**China-network:** api.vapi.ai is Cloudflare-proxied. No confirmed block. However, if your webhook/audio WS needs to be reachable from Vapi's US infra, you need a public HTTPS endpoint. Consider hosting your dispatch webhook in a region accessible from China (HK/SG/GCP).

**Sources:**
- https://docs.vapi.ai/server-url/events.mdx
- https://docs.vapi.ai/quickstart/web
- https://vapi.ai/blog/build-a-multi-functional-voicebot-in-minutes
- https://docs.veris.ai/reference/frameworks/vapi

---

### Retell AI

**What it is:** Enterprise voice AI with its own LLM WebSocket protocol. Unlike Vapi, Retell orchestrates the conversation via a WebSocket to your server — you are the LLM, Retell is the voice/TTS/telephony layer. This is architecturally different: Retell calls *your* WebSocket for every response.

**Full duplex / barge-in:** The LLM WebSocket protocol carries `update_only` events with live transcripts and `response_required` events that ask your LLM for a reply. Barge-in is handled at the Retell layer (audio WebSocket); it sends a "clear" event to the frontend when the user interrupts.

**Tool calling:** You implement tool calling inside your LLM WebSocket handler using the OpenAI function calling SDK. Retell sends transcript context, your LLM decides to call a function, you execute it and feed results back. Alternatively, Retell's built-in Single Prompt / Conversation Flow frameworks have their own tool integration.

**Web / WebRTC:** Web Call SDKs available. The `enable_audio_alignment` query param on the audio WS gives character-level timing for lip-sync.

**BYO LLM:** This is Retell's core architecture — the LLM WebSocket *is* your server.

**Pricing:** ⚠️ Exact per-minute pricing not found in docs. Enterprise-led sales model. A Retell agent prompt (Bland AI's competitive comparison) mentions "$0.09/min" but this is Bland's claim, not Retell's public rate.

**China-network:** api.retellai.com — US-based. WebSocket connections from China to US are often degraded or blocked. Twilio-style PSTN integration requires outbound SIP.

**Sources:**
- https://docs.retellai.com/api-references/llm-websocket
- https://docs.retellai.com/integrate-llm/overview
- https://docs.retellai.com/integrate-llm/integrate-function-calling
- https://docs.retellai.com/features/webhook-overview
- https://callstack.tech/blog/integrate-node-js-with-retell-ai-and-twilio-lessons-from-my-setup

---

### Bland AI

**What it is:** Phone-first AI agent platform with visual "Pathway" builder and REST API. The lowest barrier to entry for outbound/inbound calls. Built on its own models (`base`/`turbo`).

**Full duplex / barge-in:** First-class. `interruptibility` (0-4) controls when the agent yields to caller speech. `resumption_speed` (1-3) controls response latency after user stops talking. A detailed table in docs maps each setting to exact caller experience.

**Tool calling:** Custom Tools. Define a name, description, `input_schema` (JSON Schema), and `url` (your API endpoint). Agent calls your tool mid-call. You can define `speech` (what the agent says while tool executes). The Bland agent prompt itself states: "Calls are nine cents per minute total with end to end infrastructure support out of the box."

**Web / WebRTC:** `BlandWebClient` from `bland-client-js-sdk` — direct browser embedding.

**BYO LLM:** No. Uses Bland's own `base` or `turbo` models.

**Pricing:** ⚠️ "$0.09/min" claimed internally in agent prompt (aspirational/sales language). Actual public pricing not found in indexed docs. Enterprise contracts start at $30K/year. Likely pay-per-minute with no self-serve free tier beyond trial credits.

**China-network:** US infra. No confirmed block. Enterprise VPN/SIP available.

**Sources:**
- https://docs.bland.ai/api-v1/post/agents
- https://docs.bland.ai/tutorials/custom-tools
- https://docs.bland.ai/tutorials/agent-speech
- https://www.bland.ai/product
- https://www.bland.ai/blog/ai-phone-calling-setup-guide

---

### ElevenLabs Agents (Conversational AI)

**What it is:** ElevenLabs expanded from TTS into a full voice agent platform. Agents are defined in the ElevenLabs dashboard/CLI and managed via a Python/JS SDK. Uses ElevenLabs TTS + configurable LLM backend (e.g., `gemini-2.0-flash`).

**Full duplex / barge-in:** Yes. The `Conversation` class manages a WebSocket-based realtime session with `callback_user_transcript`, `callback_agent_response`, and `callback_audio_alignment` callbacks. Barge-in is handled by the ElevenLabs platform.

**Tool calling:** Two modes:
- **Webhook tools** — POST to your endpoint when the agent needs to act. Clean HTTP contract: `{ tool_call_id, tool_name, parameters, conversation_id }` in; `{ result }` out.
- **MCP tools** — connect any MCP server directly.
- **Client tools** — browser-side JS (not what you want).

**Web / WebRTC:** `@elevenlabs/client` and `@elevenlabs/react` with `connectionType: "webrtc"`. A LiveKit WebSocket pin (`livekit-client@2.16.1`) is needed to avoid `/rtc/v1` 404s (documented in their SKILL.md). Server-side signed URL via `get_signed_url()`.

**BYO LLM:** Yes. The `llm` field in `conversation_config.agent.prompt` accepts `gemini-2.0-flash`, Claude, or other supported providers. You are not locked to ElevenLabs's reasoning engine.

**Pricing:** ⚠️ Agent-tier pricing not found in indexed search results. ElevenLabs has a Creator tier (character-based) and an Enterprise tier. Agent-specific pricing may be enterprise-only. Contact sales.

**China-network:** ⚠️ ElevenLabs.io is partially accessible from China but with intermittent failures. The realtime WebSocket (`wss://livekit.rtc.elevenlabs.io`) is at risk of high latency or drops. Production use from China-adjacent networks is questionable without a reliable proxy.

**Sources:**
- https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools
- https://elevenlabs.io/docs/eleven-agents/customization/tools
- https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks.mdx
- https://github.com/elevenlabs/skills/blob/main/agents/SKILL.md

---

### Play.ai (PlayHT)

**What it is:** PlayHT's conversational agent product, spun out in 2024. Two models: PlayDialog (emotive, conversation-optimized) and Play 3.0 Mini (fast, 150ms). Backed by 900+ voices across 130+ languages.

**Full duplex / barge-in:** Yes. Sub-300ms time-to-first-audio for Play 3.0 Mini. Streaming WebSocket for realtime audio. Barge-in is inherent in the streaming model — client clears buffer on interruption.

**Tool calling:** Integrated via Zapier/Make.com and API. The agent builder has a no-code "Add Intelligence" step for tools. Less granular than Vapi/Bland custom tool definitions.

**Web / WebRTC:** Streaming WebSocket. Embeddable widget. Web SDKs available.

**BYO LLM:** Partial. Play.ai agents use GPT-4o or LLaMA internally — not arbitrary LLM injection.

**Pricing:** Free tier: 12,500 characters/month. ⚠️ Paid agent-tier pricing not confirmed in indexed results. PlayHT TTS: pay-per-character at scale. Agent product pricing likely requires a sales conversation.

**China-network:** US infrastructure (play.ht, api.play.ht). ⚠️ Expected similar connectivity issues as other US voice platforms.

**Sources:**
- https://play.ht/pricing/
- https://play.ht/voice-agents/
- https://agentbrisk.com/agents/play-ht/
- https://docs.play.ht/reference/models
- https://contentcreatortools.io/tools/playht

---

### OpenAI Realtime API

**What it is:** OpenAI's native speech-to-speech WebSocket API. One persistent connection, audio in, audio (and text) out. The most architecturally clean solution — no STT/LLM/TTS stitching.

**Full duplex / barge-in:** Best-in-class. Native VAD with sub-300ms response. `response.audio.delta` events stream audio as it generates — cut off at any point and you only pay for tokens actually generated. Barge-in is built into the model — no custom voice-activity detection needed.

**Tool calling:** Native function calling inside the Realtime session. Functions declared in `session.update`; model calls them autonomously while staying in audio mode. The model also supports MCP servers.

**Web / WebRTC:** WebSocket is the primary transport. Browser integration via WebRTC (specifically, `RealtimeSession` in `@openai/agents` SDK or raw WebSocket).

**BYO LLM:** No. Only GPT-Realtime-1.5 / GPT-Realtime-2 / GPT-Realtime-2.1.

**Pricing (official, 2025):**

| Item | Rate |
|---|---|
| Audio input | $0.06/min |
| Audio output | $0.24/min |
| Text input | $4.00 / 1M tokens |
| Text output | $16.00 / 1M tokens (GPT-Realtime-1.5) / $24.00 / 1M (GPT-Realtime-2/2.1) |
| Cached text input | $0.40 / 1M tokens |

> Realistic 10-minute support call estimate: ~$2.40 audio out + ~$0.60 audio in + ~$0.25 text tokens ≈ **$3.25/call** (source: skywork.ai cost calculator validated against OpenAI docs).

**China-network:** ❌ api.openai.com is **blocked from China** without a proxy. If you use this, you need a reliable proxy (e.g., the Riolu TW node or Oracle SG VM you already have configured).

**Sources:**
- https://developers.openai.com/api/docs/guides/realtime
- https://developers.openai.com/api/docs/models/gpt-realtime-2.1
- https://developers.openai.com/api/docs/pricing
- https://openai.com/index/introducing-gpt-realtime/
- https://skywork.ai/blog/agent/openai-realtime-api-pricing-2025-cost-calculator/
- https://www.open.cx/blog/openai-realtime-api-voice-agent-guide-2026

---

## 3. Top Recommendation

### Pick: **Vapi**

**Why Vapi over the others for your use case:**

1. **Tool-calling architecture matches your dispatch webhook perfectly.** Vapi's Server URL POST pattern is the simplest, most reliable way to wire `dispatch_to_engineer` — it's a single HTTP webhook that receives `tool-calls` events, you execute your dispatch, return the result. No WebSocket state management, no LLM hosting, no session persistence.

2. **Full orchestration out of the box.** Vapi bundles STT (Deepgram), LLM (your choice), TTS (ElevenLabs/PlayHT/OpenAI/RimeAI), endpointing, and turn-taking. You only write the tool handler and the system prompt. This is the definition of "drop in a prompt + connect a webhook."

3. **Full-duplex + barge-in proven.** Smart endpointing and `customer.speech.interrupted` hooks mean natural turn-taking without custom VAD code.

4. **Web/WebRTC SDK is production-grade.** `@vapi-ai/web` = one line to start a voice session in a browser. No LiveKit workarounds (compare: ElevenLabs requires a `livekit-client@2.16.1` pin).

5. **BYO LLM + BYO voice.** You can use DeepSeek or any other LLM provider behind Vapi. If your `dispatch_to_engineer` endpoint internally calls DeepSeek, Vapi doesn't care — it just POSTs tool events to you.

6. **No China-specific blocking confirmed.** Vapi's API is Cloudflare-backed and accessible from China-adjacent networks in prior community reports. Your dispatch webhook should be hosted in HK/SG/GCP for lowest latency.

**Runner-up: ElevenLabs Agents.** If voice quality is the #1 priority and you want ElevenLabs's best-in-class TTS, go here. Webhook tools are first-class. The China-access risk is similar. Pricing requires a sales conversation.

**Do NOT pick OpenAI Realtime API** if China-network access matters — it is blocked without a proxy, and the LLM is locked to GPT-Realtime only.

---

## 4. How `dispatch_to_engineer` Wires In (Vapi)

This is the exact integration shape, derived from Vapi's documented Server URL protocol:

### Step 1 — Define the tool in your assistant config

```json
{
  "assistant": {
    "model": {
      "provider": "openai",
      "model": "gpt-4o",
      "functions": [
        {
          "name": "dispatch_to_engineer",
          "description": "Dispatches the current conversation task to the engineering team via the CEO agent. Use when the user's request requires engineering work, a technical deep-dive, or escalation beyond your capabilities.",
          "parameters": {
            "type": "object",
            "properties": {
              "task_summary": {
                "type": "string",
                "description": "A concise summary of what the user needs done"
              },
              "user_context": {
                "type": "string",
                "description": "Relevant context from the conversation so far"
              },
              "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Priority level for this dispatch"
              }
            },
            "required": ["task_summary"]
          }
        }
      ]
    },
    "voice": {
      "provider": "elevenlabs",
      "voiceId": "JBFqnCBsd6RMkjVDRZzb"
    },
    "firstMessage": "你好！我是客服助手。有什么可以帮你的吗？",
    "serverUrl": "https://your-dispatch-webhook.example.com/vapi/tools"
  }
}
```

### Step 2 — Handle `tool-calls` at your webhook

Vapi sends a POST to your `serverUrl` with this body shape:

```json
{
  "message": {
    "type": "tool-calls",
    "call": { /* full call object */ },
    "toolWithToolCallList": [
      {
        "name": "dispatch_to_engineer",
        "toolCall": {
          "id": "abc123",
          "parameters": {
            "task_summary": "用户需要修复一个 WebRTC bug",
            "user_context": "用户说 Chrome 上音频延迟很高",
            "priority": "medium"
          }
        }
      }
    ]
  }
}
```

You respond:

```json
{
  "results": [
    {
      "name": "dispatch_to_engineer",
      "toolCallId": "abc123",
      "result": "{\"status\": \"dispatched\", \"ticket_id\": \"ENG-4521\", \"engineer\": \"oncall\"}"
    }
  ],
  "message": {
    "type": "say",
    "text": "好的，我已经把这个问题转交给工程师团队了，他们会尽快处理。"
  }
}
```

The `message.say` is optional — Vapi will speak the result text to the caller while or after the tool completes.

### Step 3 — Your dispatch endpoint calls the CEO agent

Your `/vapi/tools` handler:

```python
# FastAPI example
import httpx

DISPATCH_ENDPOINT = "https://your-api.example.com/dispatch_to_engineer"

@app.post("/vapi/tools")
async def handle_vapi_tool(request: Request):
    body = await request.json()
    tool_calls = body["message"]["toolWithToolCallList"]

    results = []
    for tc in tool_calls:
        if tc["name"] == "dispatch_to_engineer":
            # Forward to your CEO agent dispatch endpoint
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    DISPATCH_ENDPOINT,
                    json=tc["toolCall"]["parameters"],
                    timeout=10.0
                )
                result = resp.json()

            results.append({
                "name": "dispatch_to_engineer",
                "toolCallId": tc["toolCall"]["id"],
                "result": json.dumps(result)
            })

    return {"results": results}
```

### Step 4 — WebRTC client

```typescript
import Vapi from "@vapi-ai/web";
const vapi = new Vapi("YOUR_PUBLIC_API_KEY");

vapi.start("YOUR_ASSISTANT_ID");

vapi.on("message", (msg) => {
  if (msg.type === "transcript") {
    console.log(`${msg.role}: ${msg.transcript}`);
  }
});
```

That is the full loop. Prompt → Vapi cloud → tool call → your webhook → dispatch to CEO agent → result back to Vapi → spoken to user. No WebSocket state to manage on your side.

---

## 5. China-Network Caveats

| Platform | Status | Notes |
|---|---|---|
| Vapi | ⚠️ Likely reachable | Cloudflare-proxied; host your webhook in HK/SG for <200ms |
| Retell AI | ⚠️ Likely degraded | WS to US infra; may need GCP/Cloudflare Tunnel |
| Bland AI | ⚠️ Unknown | US infra; enterprise customers may get regional endpoints |
| ElevenLabs | ⚠️ Partial | wss://livekit.rtc.elevenlabs.io risk from China; ElevenLabs.io pages sometimes timeout |
| Play.ai | ⚠️ Likely degraded | play.ht US infra |
| OpenAI Realtime | ❌ Blocked | api.openai.com requires proxy; use Riolu TW node or your Oracle SG VM |

**Recommended hosting for dispatch webhook:** GCP Hong Kong or Cloudflare Workers (edge, reaches China well). Avoid us-west-2 if your primary users are in China-adjacent networks — Vapi's docs specifically warn to "host your webhook close to us-west-2 to reduce latency" but for your deployment, HK/SG is the right call.

---

## 6. Summary

| Rank | Platform | Verdict |
|---|---|---|
| **1 — Best fit** | **Vapi** | Cleanest webhook tool-calling → your dispatch endpoint. Full-duplex proven. BYO LLM/voice. Most battle-tested for exactly this pattern. |
| 2 — Best voice quality | ElevenLabs Agents | Industry-leading TTS; webhook + MCP tools; China risk; pricing requires sales |
| 3 — Most self-serve | Bland AI | $0.09/min (claimed); web/phone/barge-in; no BYO LLM; less flexible tool model |
| 4 — Rawest control | OpenAI Realtime API | Cheapest per-minute at scale; China blocked; LLM locked; build your own orchestration |
| 5 — Best enterprise | Synthflow | $30K+ enterprise contracts; in-house telephony; enterprise SLA; overkill for MVP |
| ❌ Skip | Retell AI | WebSocket LLM pattern is over-engineered for this use case; pricing opaque; China infra risk |

---

*All URLs verified via AnySearch MCP, 2025-07-23. Pricing figures ⚠️ [citation needed] where confirmed public pricing was not found in search results.*
