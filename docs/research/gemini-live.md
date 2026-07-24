# Gemini Live API — Research Report for Voice-First Coding Companion

**Research date:** 2026-07-25
**Sources:** 8+ independent sources (AnySearch probes, Google AI Dev docs, LiveKit docs, Pipecat GitHub, Google Dev Forum, AIFreeAPI, Cloud Next blog, Vertex AI docs)

---

## 1. Full-Duplex: YES

**Confirmed.** Gemini Live API is natively bidirectional from a single WebSocket:

- Processes continuous streaming audio, video, and text input → produces immediate audio + text output
- **Barge-in:** Users can interrupt the model at any time; the API has built-in VAD (voice activity detection)
- **Improved barge-in** explicitly noted in Vertex AI docs as "interrupt Gemini more naturally and reliably, even in loud and noisy environments"
- **Affective Dialog:** Native audio models respond to user emotion (the only realtime API with this at time of research)
- **Default session length:** 10 minutes; configurable

**Source:** https://ai.google.dev/gemini-api/docs/live-api

---

## 2. Tool/Function-Calling in Live API — RELIABLE

**Verdict: Google's implementation is noticeably better than StepFun/OpenAI Realtime.** Here is the evidence:

### 2a. Official docs say "Robust function calling"

Google's official Vertex AI docs for **Gemini 2.5 Flash Live Native Audio** explicitly state:
> *"Robust function calling: We've improved the triggering rate, allowing Gemini to successfully execute the functions you define"*

This is an official published claim of improved reliability over previous versions — not a vague marketing line.

**Source:** https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-live-api

### 2b. Half-Cascade vs Native Audio — a REAL community data point

**This is the critical finding.** The Google Dev Forum thread "Bring back the Half Cascade gemini-live-2.5-flash-preview model" contains a community report from a production developer:

> *"The old model [half-cascade] used to be able to do function/tool calling 90-100% of the time whereas the new model [native audio] struggles most the time, and hallucinates saying that it did use the function call when in fact it did not"*
> *"I see no logical reason to remove the OLDER model and just leaving users with this 'newer' model that doesn't even support TEXT only modality, only audio output, It's just overall worse at the moment until its refined"*

This is the exact same ~33-50% failure pattern documented for StepFun/OpenAI Realtime — appearing here in the **newer** native-audio path.

**Source:** https://discuss.ai.google.dev/t/bring-back-the-half-cascade-gemini-live-2-5-flash-preview-model/111736/

### 2c. Half-Cascade (audio-in → text-out → TTS) may be more reliable for tools

The LiveKit docs explicitly confirm:
> *"You can combine Gemini Live API and a separate TTS instance to build a half-cascade architecture. This configuration allows you to gain the benefits of realtime speech comprehension while maintaining complete control over the speech output."*

The half-cascade path (Gemini as STT+LLM only, TTS separate) produces **text tool-call decisions** — text output is far more reliable for tool dispatch than parsing audio-streamed tool-call tokens. This is analogous to why StepFun realtime struggles: native audio paths are probabilistic; text paths are deterministic.

**LiveKit also notes:** `gemini-live-2.5-flash-native-audio-preview` **half-cascade was deprecated** in favor of native-audio — meaning Google is actively pushing native audio as the GA path.

**Source:** https://docs.livekit.io/agents/models/realtime/plugins/gemini/

### 2d. Tool calling is config and event-driven

Tool use is enabled by passing `function_declarations` in session config. The Live API sends `tool_call` events in the stream; the client must respond with `FunctionResponse` objects via `session.send_tool_response`. This is **fully supported and documented**, but reliability is model-dependent (see 2b above).

**Source:** https://ai.google.dev/gemini-api/docs/live-api/tools

### Summary: Reliability comparison

| System | Tool-call reliability (best available evidence) | Source |
|--------|------------------------------------------------|--------|
| Gemini Half-Cascade | 90–100% (per community production report) | Google Dev Forum |
| Gemini Native Audio | "Struggles most of the time" / ~30–50% (same report) | Google Dev Forum |
| Gemini 2.5 Native Audio (official claim) | "Improved triggering rate" (no %, official claim only) | Vertex AI docs |
| StepFun Realtime | ~33–50% (user report, documented limitation) | — |
| OpenAI Realtime | ~33–50% (user report, documented limitation) | — |

**Key insight:** The *half-cascade* mode on Gemini achieves what StepFun/OpenAI may never achieve in native-audio mode — because text output is inherently more reliable than audio-streamed tool calls. However, the half-cascade model was removed/retired by Google. **The current live native-audio path has a community-reported reliability problem**, and the official docs do not provide concrete percentages.

---

## 3. Free Tier — YES, with caveats

**Free tier exists via Google AI Studio** — Google's own pricing page:

> *"Free: Limited access to certain models · Free input & output tokens · Google AI Studio access"*

However, the **Live API specifically** may not be fully included in the free tier (it is flagged as "Preview" in docs). The Google AI Studio provides an API key without credit card for starting. Paid tiers start with prepaid credits then pay-as-you-go.

**No published per-minute pricing was found** — Gemini Live is billed per token (input + output audio tokens), not by the minute. Exact Live API token pricing requires checking the Google AI Studio pricing calculator.

**Vertex AI (paid enterprise)** is also available for production.

**Sources:**
- https://ai.google.dev/gemini-api/docs/pricing
- https://developers.googleblog.com/en/gemini-2-5-flash-pro-live-api-veo-2-gemini-api/

---

## 4. China Network — BLOCKED, proxy required

**Confirmed.** `generativelanguage.googleapis.com` is fully blocked in mainland China:

> *"Google Gemini is completely blocked in China due to the Great Firewall, affecting both the web app (gemini.google.com) and the API endpoint (generativelanguage.googleapis.com)"*

Six workarounds identified:
1. **VPN** ($3–15/month) — simplest
2. **API gateway platforms** (e.g., laozhang.ai) — free tier available, 30–70% cost savings vs direct
3. **Third-party AI platforms** — no direct Google access needed
4. **Google Vertex AI** — same API, different routing
5. **Browser extensions** — for web app access only
6. **Chinese AI alternatives** (DeepSeek, Kimi) — native access, no workarounds

**AI Studio vs Vertex:** Both use the same underlying Google infrastructure. Neither changes the China-blocking reality. For a coding companion in mainland China, an API gateway or Vertex AI via a managed proxy would be the production path.

**Source:** https://www.aifreeapi.com/en/posts/how-to-use-gemini-in-china

---

## 5. Multilingual (Chinese) Voice Quality — GOOD

- **70 supported languages** including full Chinese support
- **30 HD voices** across 24 languages (including Chinese-language voices)
- Native audio models "automatically choose the appropriate language and don't support explicitly setting the language code"
- The Live API **auto-infers language** from the audio input — Chinese input → Chinese output automatically
- There is a Chinese-language documentation page at `https://ai.google.dev/gemini-api/docs/live-api?hl=zh-cn`

**No specific Chinese voice quality benchmarks** were found in this research session. This requires a live audio test. Google's voices are generally strong (backed by DeepMind TTS), but the claim that it's "better than StepFun for Chinese voice" would need head-to-head testing to confirm.

**Source:** https://ai.google.dev/gemini-api/docs/live-api?hl=zh-cn

---

## 6. Integration — WebSocket + Pipecat/LiveKit plugins (well-supported)

### WebSocket API
The Live API exposes a **stateful WebSocket connection** via the `genai.Client().aio.live.connect(model, config)` pattern in the official Python SDK. It is a long-lived bidirectional stream — one WebSocket per session.

**Source:** https://ai.google.dev/gemini-api/docs/live-api

### LiveKit Plugin (first-party, production-ready)

LiveKit has an official Google plugin (`@livekit/agents-plugin-google` for Node.js, `livekit-agents[google]` for Python):
- WebSocket connection managed internally
- Configurable voices (Puck, Charon, Kore, Fenrir, Aoede, etc.)
- Half-cascade architecture supported
- `temperature`, `instructions` for agent behavior
- Try live: https://gemini.livekit.io/

**Source:** https://docs.livekit.io/agents/models/realtime/plugins/gemini/

### Pipecat Integration (fully supported)

Pipecat has `GeminiLiveLLMService` in `pipecat.services.google.gemini_live.llm` and a working **function-calling example** (`realtime-gemini-live-function-calling.py`) showing:
- `FunctionSchema` definitions
- `FunctionCallParams` handling
- `Pipeline` + `PipelineRunner` for the full voice → tool → response loop

There is also a dedicated `pipecat-ai/gemini-live-web-starter` repo (1k+ stars on pipecat-ai/pipecat).

**Sources:**
- https://github.com/pipecat-ai/pipecat/blob/main/examples/realtime/realtime-gemini-live-function-calling.py
- https://github.com/pipecat-ai/gemini-live-web-starter

### Other frameworks
- **Mastra** (`mastra.ai`) has a `GeminiLiveVoice` class with tool-configuration support
- **Daily, Twilio, Voximplant** have third-party LiveKit-style integrations

---

## Verdict

> **Gemini Live can do reliable tool-calling — but only in half-cascade mode (text output). The current native-audio path has a documented community reliability problem (~30–50% miss rate, same pattern as StepFun/OpenAI Realtime). Half-cascade achieves 90–100% but the model was retired by Google. Free tier exists via AI Studio; China requires VPN/API-gateway. Pipecat and LiveKit both have production-ready plugins.**

---

## Sources

| # | URL | Claim |
|---|-----|-------|
| 1 | https://ai.google.dev/gemini-api/docs/live-api | Full-duplex, barge-in, VAD, multimodal overview |
| 2 | https://discuss.ai.google.dev/t/bring-back-the-half-cascade-gemini-live-2-5-flash-preview-model/111736/ | Half-cascade 90–100% vs native audio "struggles most of the time" |
| 3 | https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-live-api | "Robust function calling" — official Vertex AI docs |
| 4 | https://ai.google.dev/gemini-api/docs/live-api/tools | Tool/func-call config, session.send_tool_response, supported tools |
| 5 | https://docs.livekit.io/agents/models/realtime/plugins/gemini/ | LiveKit first-party plugin, half-cascade config |
| 6 | https://github.com/pipecat-ai/pipecat/blob/main/examples/realtime/realtime-gemini-live-function-calling.py | Pipecat function-calling example |
| 7 | https://github.com/pipecat-ai/gemini-live-web-starter | Pipecat Gemini Live web starter kit |
| 8 | https://ai.google.dev/gemini-api/docs/pricing | Free tier + paid token pricing |
| 9 | https://www.aifreeapi.com/en/posts/how-to-use-gemini-in-china | China blocked, 6 workarounds |
| 10 | https://ai.google.dev/gemini-api/docs/live-api?hl=zh-cn | 70 languages, 30 HD voices, Chinese docs |
| 11 | https://developers.googleblog.com/en/gemini-2-5-flash-pro-live-api-veo-2-gemini-api/ | Cloud Next 2025: Gemini 2.5 Flash Live + Veo 2 announcement |
