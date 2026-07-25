# Phone Integration Handoff — for Codex

**Project:** AnyVibe / coding-vibe — voice-first AI coding companion (AdventureX 2026)
**Worktree:** `/Users/onezion12344/Projects/adv-x/coding-vibe/coding-vibe-qoder`
**Branch:** `feat/qoder-company`
**Written:** 2026-07-25 · Demo Day 2026-07-26
**Two approaches to give the agent a phone number / messaging identity:**
1. **Twilio** — real PSTN phone call. **CODE IS DONE & COMMITTED.** Needs account finish + wiring + live test.
2. **Photon Spectrum** — 8-channel messaging identity (iMessage/Telegram/etc). **RESEARCHED, NOT BUILT.** Full plan below.

> ⚠️ **Before you start:** this worktree has active work. Do NOT overwrite `web/static/index.html`, `docs/landing.html`, or any `web/static/*` files — they are hand-designed. Phone work is confined to `voice/*.py` and (for Photon) new files `web/photon.py` + a `sidecar/` dir. Stay in your lane.

---

# APPROACH 1 — Twilio (real phone call) — IMPLEMENTED

## Status: code committed, needs account + env + live test

The bridge code already exists on `feat/qoder-company`, committed across 4 commits:

| Commit | What |
|--------|------|
| `978b46f` | `voice/telephony_audio.py`, `voice/outbound.py`, `/twilio-voice` + `/twilio-stream` in `voice/server.py` |
| `4365712` | token gate + concurrency cap on `/twilio-stream` |
| `67ea84d` | short-lived capability token in Stream URL + X-Twilio-Signature validation + counter-leak fix |
| `182703e` | fail-closed on missing SDK + pin signed-URL host (not client headers) |

## Architecture
```
Phone call → Twilio number → Twilio Media Streams (μ-law 8kHz, bidirectional WS)
   → wss://<public>/twilio-stream  (voice/server.py)
   → telephony_audio: μ-law 8k → PCM16 24k
   → StepFun Realtime API (step-1o-audio, speech-to-speech)
   → PCM16 24k → μ-law 8k → back to Twilio → caller hears the Yellow Sheep

Callback: voice/outbound.py → Twilio Calls API dials the user's verified mobile,
          connects it to the same /twilio-stream bridge ("agent calls you back").
```

## Files (all absolute)
- `/Users/onezion12344/Projects/adv-x/coding-vibe/coding-vibe-qoder/voice/telephony_audio.py` — μ-law↔PCM16 codec + 8k↔24k resample (native `audioop`, numpy fallback for Py3.13)
- `/Users/onezion12344/Projects/adv-x/coding-vibe/coding-vibe-qoder/voice/server.py` — `POST /twilio-voice` (returns TwiML) + `WS /twilio-stream` (bridge)
- `/Users/onezion12344/Projects/adv-x/coding-vibe/coding-vibe-qoder/voice/outbound.py` — `call_me_back()` outbound callback

## ⚠️ Known bug to fix first (1 line)
In `voice/server.py`, `from voice.telephony_audio import ...` sits ABOVE the `sys.path.insert(_WORKTREE_ROOT)` line. Module import works, but running `python3 voice/server.py` directly may fail to resolve the `voice` package. **Fix:** move that import to just below the `sys.path.insert(...)` line, or run the server as a module (`python3 -m voice.server`) from the repo root.

## Twilio account state (signup started, NOT finished)
- Account created: **Account SID `US1af5ebae2e7d7c5751aea0948078f634`**
- Login: `onezion12344@gmail.com` (password is in the owner's password manager — NOT in this doc)
- **Remaining manual steps (owner must do — needs email/SMS codes):**
  1. Verify email code + verify phone (**HK mobile +852 53782215** — keeps trial in HK context)
  2. Onboarding: Voice / Python / Build my own
  3. Buy a **US local** voice number (HK DIDs need regulatory bundles — unavailable on trial)
  4. Verified Caller IDs → add **+852 53782215** (trial only calls verified numbers)
  5. **Voice → Settings → Geo Permissions → enable Hong Kong** (else +852 calls silently fail, error 21215)
  6. Set the number's Voice webhook → `https://<public-host>/twilio-voice` (HTTP POST)
  7. Copy the **Auth Token** from the console dashboard

## Env vars to set (in `.env`, never commit)
```bash
STEPFUN_API_KEY=...            # already set
CV_API_TOKEN=...               # REQUIRED — turns on the /twilio-stream token gate (else dev-mode allows all)
TWILIO_ACCOUNT_SID=US1af5ebae2e7d7c5751aea0948078f634
TWILIO_AUTH_TOKEN=...          # from console — turns on X-Twilio-Signature validation
TWILIO_FROM=+1...              # your US Twilio number
TWILIO_TO_VERIFIED=+85253782215
CV_PUBLIC_WSS=wss://<public-host>/twilio-stream
CV_MAX_TWILIO_STREAMS=4        # optional, default 4
```

## Public exposure (Twilio must reach a public TLS URL)
```bash
# Throwaway (fastest for demo):
cloudflared tunnel --url http://localhost:7860
#   → use https://<random>.trycloudflare.com/twilio-voice as the webhook
#   → and wss://<random>.trycloudflare.com/twilio-stream as CV_PUBLIC_WSS
# Or the named tunnel on *.onezion.top (twilio.onezion.top) — see repo hosting notes.
```

## Deps
```bash
/Users/onezion12344/miniforge3/bin/python3 -m pip install twilio "requests[socks]"
```

## Test plan
1. **Codec smoke test (no phone):**
   ```bash
   cd /Users/onezion12344/Projects/adv-x/coding-vibe/coding-vibe-qoder
   /Users/onezion12344/miniforge3/bin/python3 -c "from voice.telephony_audio import pcm24k_to_ulaw8k, ulaw8k_to_pcm24k; u,_=pcm24k_to_ulaw8k(b'\x01\x00'*2400,None); p,_=ulaw8k_to_pcm24k(u,None); print('ulaw',len(u),'pcm',len(p))"
   # expect ~800 μ-law bytes, non-empty pcm
   ```
2. **Server + tunnel up**, hit `https://<host>/twilio-voice` in a browser → should return `<Response><Connect><Stream .../></Connect></Response>` XML.
3. **Inbound:** dial the Twilio number from the verified +852 phone → hear the Yellow Sheep receptionist; watch logs for `[twilio] stream started (sid=...)`.
4. **Outbound:** `python3 voice/outbound.py` → verified phone rings → connects to the agent.

## Security model (already built — don't remove)
- `/twilio-stream` rejects unauthorized/over-cap connections before `accept()`; token is a short-lived capability minted per call (not the long-lived secret).
- `/twilio-voice` validates `X-Twilio-Signature` when `TWILIO_AUTH_TOKEN` is set; fails closed if the twilio SDK can't load; signed-URL host pinned to `CV_PUBLIC_WSS` (not client headers).
- Concurrent StepFun sessions capped at `CV_MAX_TWILIO_STREAMS` (default 4).

## Gotchas
- 8kHz telephony sounds narrowband vs StepFun's 24kHz — expected, not a bug.
- Latency: Phone→Twilio→Cloudflare→Mac→StepFun adds ~0.5–1.5s; keep receptionist replies short.
- Trial plays a "trial account" preamble + may need a keypress; upgrade (~$20) removes it.
- Outbound REST call from mainland China needs `HTTPS_PROXY` (SG SOCKS / Riolu) — see `voice/outbound.py` docstring.
- **Fallback if the phone path breaks at the venue:** the browser WebRTC call UI (`/` on :7860, talks to StepFun via `/ws`) is fully independent of Twilio. Keep it as the safety net.

---

# APPROACH 2 — Photon Spectrum (messaging identity) — RESEARCHED, NOT BUILT

## What it is (verified 2026-07)
**Photon** (photon.codes, "the Twilio for AI agents") — **Spectrum** connects agents to real messaging surfaces instead of a web chat box. Open-source TS SDK + managed cloud. Docs: https://docs.photon.codes · dashboard: https://app.photon.codes · SDK: https://github.com/photon-hq/spectrum-ts. **This is the AdventureX Photon track sponsor** (「给你的 Agent 一个手机号」).

## Access (deadline-critical)
- **Self-serve signup works now** at https://app.photon.codes → create project → get `projectId` + `projectSecret` in minutes. No waitlist for free tier.
- **Free tier:** iMessage on shared line pool (real number, SMS/RCS fallback, ≤10 users) + Telegram + SMS included. Enough for a demo.
- **Hackathon perks:** Photon Builders program (credits + doubles your prize if you win using Spectrum) — grab at the **booth / AdventureX Feishu group** day 1. Also confirm on-site whether a free iMessage line can text a **+86** number (US-centric pool — Telegram sidesteps this).

## KEY CONSTRAINT: no Python SDK
- **Inbound** = pure-Python webhook (fine).
- **Outbound** = requires a small **Node `spectrum-ts` sidecar** on loopback (the only unavoidable TS). ~2h to build. This is the proven pattern (Hermes Agent ships it).

## Channels: live vs marketing
- **Live:** iMessage, WhatsApp Business, Telegram, Slack, SMS/RCS.
- **NOT native (do not promise in demo):** Signal, Teams, Discord.

## Integration plan (maps onto existing AnyVibe code)
AnyVibe already has the exact shape: inbound intent path `web/engineer_dispatch.py::classify_and_dispatch(transcript, on_dispatched)`, and an outbound completion hook in `receptionist/core.py` / `web/engineer_dispatch.py` `_on_complete` (today calls `web/signaling.py::ring`). Photon slots in as a new transport on both ends — reuse all dispatch/CEO logic untouched.

**Topology:** Inbound = Spectrum webhook → FastAPI (Python). Outbound = tiny Node sidecar. Reuse `classify_and_dispatch` verbatim.

### Step 1 — provision
1. Sign up at app.photon.codes, project "AnyVibe", set `PHOTON_PROJECT_ID` + `PHOTON_PROJECT_SECRET` in `.env`.
2. Enable **Telegram** (most reliable for a China demo) + iMessage.
3. Register the webhook (Python, matches Photon's own example):
   ```python
   import httpx, os
   r = httpx.post(
       f"https://spectrum.photon.codes/projects/{os.environ['PHOTON_PROJECT_ID']}/webhooks/",
       auth=(os.environ['PHOTON_PROJECT_ID'], os.environ['PHOTON_PROJECT_SECRET']),
       json={"webhookUrl": "https://<public-host>/photon-webhook"})
   print(r.json()["data"]["signingSecret"])  # store as PHOTON_SIGNING_SECRET — shown once
   ```

### Step 2 — inbound: new file `web/photon.py`
```python
"""web/photon.py — Spectrum webhook: inbound messages -> engineer dispatch."""
from __future__ import annotations
import hashlib, hmac, json, os, time
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from web.engineer_dispatch import classify_and_dispatch

router = APIRouter(tags=["photon"])
SIGNING_SECRET = os.environ.get("PHOTON_SIGNING_SECRET", "")
_SPACES: dict[str, dict] = {}   # sender_id -> space (so on_complete can reply proactively)

def _verify(raw: bytes, ts: str, sig: str) -> bool:
    if not SIGNING_SECRET or not ts or not sig:
        return False
    if abs(int(time.time()) - int(ts)) > 300:      # 5-min tolerance
        return False
    expected = "v0=" + hmac.new(SIGNING_SECRET.encode(), f"{ts}.".encode() + raw,
                                hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)

@router.post("/photon-webhook")
async def photon_webhook(request: Request) -> JSONResponse:
    raw = await request.body()                      # RAW bytes — do NOT use a Pydantic model
    if not _verify(raw, request.headers.get("X-Spectrum-Timestamp", ""),
                        request.headers.get("X-Spectrum-Signature", "")):
        return JSONResponse({"error": "bad signature"}, status_code=401)
    body = json.loads(raw)
    msg, space = body.get("message") or {}, body.get("space") or {}
    if (msg.get("content") or {}).get("type") != "text":
        return JSONResponse({"ok": True})
    text = msg["content"]["text"]
    sender = (msg.get("sender") or {}).get("id", "")
    _SPACES[sender] = {"space": space, "platform": msg.get("platform")}

    def _on_dispatched(info: dict) -> None:
        from web.photon_send import send_message
        send_message(space, f"收到，已交给工程团队：{info.get('task','')}（#{info.get('task_id','')}）")

    await classify_and_dispatch(text, _on_dispatched)   # <- 100% reuse
    return JSONResponse({"ok": True})
```
Mount in `web/server.py` like the other routers: `app.include_router(photon.router)`.

### Step 3 — outbound: Node sidecar + Python shim
`sidecar/send.mjs`:
```js
import http from "node:http";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { telegram } from "spectrum-ts/providers/telegram";
const app = await Spectrum({ projectId: process.env.PHOTON_PROJECT_ID,
  projectSecret: process.env.PHOTON_PROJECT_SECRET,
  providers: [imessage.config(), telegram.config()] });
http.createServer(async (req, res) => {
  let b = ""; for await (const c of req) b += c;
  const { space, text } = JSON.parse(b);
  await app.send(space, text);
  res.writeHead(200).end("ok");
}).listen(8790, "127.0.0.1");
```
`web/photon_send.py`:
```python
import httpx
def send_message(space: dict, text: str) -> None:
    httpx.post("http://127.0.0.1:8790/send", json={"space": space, "text": text}, timeout=8.0)
```

### Step 4 — proactive completion (the differentiator)
Hook into the existing `_on_complete` in `web/engineer_dispatch.py` (currently only calls `ring()`); add a Photon send ALONGSIDE it (complement, don't replace):
```python
    async def _on_complete(result):
        # ... existing state update + ring() unchanged ...
        try:
            from web.photon_send import send_message
            summary = (getattr(result, "summary", "") or "")[:200]
            space = _photon_space_for(tid)          # populate at dispatch time from _SPACES
            if space:
                send_message(space, f"✅ 完成：{summary}")
        except Exception as exc:
            _log("DISPATCH", f"photon notify failed (non-fatal): {exc}")
```

## Env vars
```bash
PHOTON_PROJECT_ID=...
PHOTON_PROJECT_SECRET=...
PHOTON_SIGNING_SECRET=...   # from webhook registration (shown once)
```

## Killer demo (matches the track thesis)
Pull the agent into a **group chat** (Telegram/iMessage), `@AnyVibe fix the login bug` → webhook → `classify_and_dispatch` → CEO/team runs → `on_complete` → agent replies **in the same thread**: "✅ Done — patched auth.py, here's the diff" (+ optional voice note via StepFun TTS as Spectrum `voice` content). The conversation IS the interface. Gate on @-mention so it only acts when addressed.

## Realistic scope for Demo Day + fallbacks
- **Do:** ONE channel end-to-end = **Telegram** (free, not Apple-gated, works from China) + proactive completion message.
- **Stretch:** add iMessage if the booth confirms it reaches the demo number; add a voice-note reply.
- ⚠️ **Cold outreach** (agent messages a user who never messaged first) is Business-tier only. Design the demo as **user-messages-first** (or agent-in-group-first), then the completion reply lands in that established space — no cold-outreach entitlement needed, and it's the natural flow.
- **Fallbacks (zero new risk):** if Spectrum access/number can't be obtained → keep the existing `web/signaling.py` ring + browser call as the "agent calls you back" demo; if the Node sidecar is flaky → inbound-only (agent receives on Telegram, replies via browser/phone UI).

## Sources
- https://docs.photon.codes/ · https://photon.codes/ (/pricing, /builders) · https://github.com/photon-hq/spectrum-ts
- Hermes Agent Photon integration (Python-sidecar reference): https://hermesagent.org.cn/docs/user-guide/messaging/photon

---

# Which to prioritize?
- **Twilio** = closest to done (code committed), makes a *real phone ring* — highest "wow" for the callback story, but needs the owner to finish Twilio signup + set env.
- **Photon** = better fit for **Track #24** and a stronger on-thesis demo (messaging as interface, group chat), but requires building the webhook + Node sidecar and confirming access on-site.
- **Both share the same dispatch backend** — neither blocks the core demo (browser voice + kanban). Treat both as bonus tracks.
