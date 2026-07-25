# Marketing Plan — Coding Vibe (AdventureX 2026)

**Demo Day: 2026-07-26** | Track #04 Qoder「一个人=一支工程团队」
**Booth + 5-min stage pitch** | Repo: `onezion12344/coding-vibe`

---

## 1. GitHub README Polish

Goal: a README that a judge can scan in 60 seconds and understand the architecture, demo flow, and "why this wins."

### Changes to make:
- **Add architecture diagram** — inline SVG showing the full loop: User Voice → CS Receptionist (黄羊) → Text LLM Brain → Qoder CEO → Role Team fan-out → Kanban → Callback
- **Add demo GIF/screenshot** — placeholder with instructions for what to capture
- **Add "Quick Try" section** — exact commands for local demo (server + voice + kanban)
- **Add sponsor acknowledgments** — Viaim, Qoder, StepFun banners/links
- **Add the tagline** — "Yesterday we brought Vibe into Coding. Today we merge Coding into Vibe."
- **Move architecture to a diagram section** — keep the ASCII art but supplement with a visual

### Specific README edits (current file: `README.md`):

1. **After the opening paragraph**, add tagline and sponsor badges
2. **Replace ASCII architecture** with a combined approach: keep ASCII for docs, add an inline SVG for the README hero
3. **Add a "Quick Try (60 seconds)" section** after the hook setup:
   ```bash
   cd coding-vibe-qoder
   source .venv/bin/activate
   ./web/run.sh  # starts on :5091
   # Open http://localhost:5091/call?token=<CV_API_TOKEN>
   # Open http://localhost:5091/company in another tab
   ```
4. **Add a "Demo GIF" section** with a placeholder and capture instructions:
   - Capture: call in via voice → task appears on kanban → agent calls back
   - Screen recording: QuickTime, crop to 480px width
5. **Add "Built With" sponsor section** at the bottom:
   - Viaim (科大讯飞 headset SDK) — voice input hardware
   - Qoder — multi-agent orchestration backend
   - StepFun 阶跃星辰 — voice AI models (STT + LLM + TTS)

---

## 2. Demo Video — 90-Second Script

### Storyboard

| Time | Visual | Audio / Narration |
|------|--------|-------------------|
| 0:00-0:10 | Title card: "Coding Vibe" with tagline, deep space bg | "Yesterday we brought Vibe into Coding. Today we merge Coding into Vibe." |
| 0:10-0:25 | Phone in hand, earphones in, walking/cycling POV | "You're on the go. No laptop. No keyboard. Just your voice." |
| 0:25-0:40 | Tap "Call CS Receptionist" → dialing animation → connected | "Call the Yellow Sheep receptionist. Describe your task in natural language — like calling a colleague." |
| 0:40-0:55 | Split screen: voice waveform + kanban lighting up. Task cards move from Pending → In Progress → Done | "Behind the scenes: a text LLM brain decides the work, dispatches to a Qoder CEO, who fans out a preset role team. Every agent's work streams onto a live kanban." |
| 0:55-1:10 | Phone screen: incoming call from "Coding Vibe · CEO". Accept → voice summary of what was done | "When the work is done, the agent calls YOU back. No screen-checking. No polling. Bidirectional voice — this is the differentiator." |
| 1:10-1:25 | Montage: cycling, walking, driving — always with earphones | "Codex has voice. But we can call in AND they can call us back. That's the killer feature." |
| 1:25-1:30 | Title card: "Coding Vibe" + GitHub QR code + AdventureX 2026 logo | "Try it at github.com/onezion12344/coding-vibe" |

### Recording Instructions
- Record the web UI (http://localhost:5091/call) at 480px mobile width
- Use QuickTime screen recording + iPhone audio for voice
- Edit in CapCut or iMovie
- Export 1080p, 30fps, H.264
- Add subtitles (Chinese + English)

---

## 3. On-Site Pitch — 5-Minute Outline

### Structure

**0:00-0:30 — The Problem (Hook)**
- "Raise your hand if you've ever wanted to code while walking, cycling, or driving."
- "Now raise your hand if you've ever waited for a build to finish, refreshing a screen."
- "What if your computer worked for YOU — and called you when it was done?"

**0:30-1:30 — What is Coding Vibe?**
- Voice-first AI coding companion via earphones
- Call the Yellow Sheep receptionist (黄羊), speak naturally
- AI team works invisibly: CS → text LLM brain → Qoder CEO → role team
- You get a phone call back when work is complete
- Bidirectional calling is the wedge — Codex can't call you back

**1:30-3:00 — Live Demo**
- Show the call UI on screen (mirror phone or show the web UI)
- Call in: "给 landing page 加一个 dark mode toggle，然后跑一下测试"
- Show kanban lighting up in real-time (second tab: /company)
- Show role team fan-out: Architect analyzes → Builder codes → Reviewer checks
- Wait for callback → accept → agent speaks the result
- **Backup plan if demo fails:** Pre-recorded video (see section below)

**3:00-4:00 — How It Works (Architecture)**
- Show architecture diagram
- CS receptionist (StepFun stepaudio-2.5-realtime) — voice only, no code
- Text LLM brain (StepFun step-3.7-flash) — intent classification + dispatch decision
- Qoder CEO — persistent agent, manages role team
- Role team: Architect, Builder, Reviewer, Tester
- Inter-agent comms → LLM-summarized → live kanban
- Callback via WebSocket signaling + native push

**4:00-4:30 — Why This Wins (Differentiator)**
- Codex has voice. We have bidirectional voice + persistent team + live kanban.
- Not a personal assistant — the CEO of your engineering company
- Works while cycling, walking, driving — no hands, no eyes

**4:30-5:00 — Vision + CTA**
- Future: XR glasses, smart rings, always-on monitoring, one-person company
- Built with Viaim + Qoder + StepFun 阶跃星辰
- "为创造，再一次信仰之跃"
- QR code to GitHub + landing page

### Backup Plan if Demo Fails
1. **Pre-recorded demo video** (the 90-second video above) — always ready
2. **Still screenshots** of each step, narrate over them
3. **Live kanban-only demo** — the board works independently; show it updating even if voice fails
4. **Worst case: architecture walkthrough** — the concept is strong enough on its own

---

## 4. Booth Materials

### On-Screen Display
- **Main screen:** Landing page (docs/landing.html) in a browser, fullscreen
- **Secondary screen (tablet/phone):** The actual call UI (http://localhost:5091/call), ready for live demos
- **Third screen (optional):** Company kanban (http://localhost:5091/company) showing a running demo

### One-Liner Poster (A3, vertical)
```
╔════════════════════════════════╗
║                                ║
║     🐑  CODING VIBE            ║
║                                ║
║  "昨天我们把 Vibe 带进了        ║
║   Coding。今天，我们把         ║
║   Coding 融入了 Vibe。"        ║
║                                ║
║  Voice-first AI coding.        ║
║  Call in. Speak naturally.     ║
║  AI team works.                ║
║  They call YOU back.           ║
║                                ║
║  ┌──────────────────────────┐  ║
║  │  TRY IT                   │  ║
║  │  onezion12344.github.io   │  ║
║  │  /projects/coding-vibe/   │  ║
║  └──────────────────────────┘  ║
║                                ║
║  Built with Viaim · Qoder     ║
║  · StepFun 阶跃星辰            ║
║                                ║
║  AdventureX 2026 · Track #04  ║
║  "为创造，再一次信仰之跃"       ║
║                                ║
╚════════════════════════════════╝
```

### QR Code
- Link: `https://onezion12344.github.io/projects/coding-vibe/`
- Print on sticker/postcard with text: "Talk to an AI engineering team"
- Generate with: `qrencode -o qr-booth.png "https://onezion12344.github.io/projects/coding-vibe/"`

### Handout Card (business card size)
- Front: "Coding Vibe" + tagline + QR code
- Back: "Call an AI engineering team. They call you back." + GitHub URL

---

## 5. Promotion Checklist (Before Demo Day)

- [ ] README polished (diagram, sponsors, quick start)
- [ ] Demo video recorded + uploaded (YouTube unlisted or local file)
- [ ] Landing page deployed (docs/landing.html → GitHub Pages)
- [ ] Call UI tested end-to-end (voice → dispatch → kanban → callback)
- [ ] Poster printed (A3, color)
- [ ] QR code stickers printed
- [ ] Backup video on local disk (no network dependency)
- [ ] Booth power strip + phone charging cable
- [ ] Earphones for demo (Viaim headset if available)
- [ ] Two phones/tablets: one for demo, one showing kanban

---

## 6. Judge Talking Points

**Qoder judges** (track #04):
- Persistent company architecture: the CEO + role team survives across tasks
- Inter-agent comms are LLM-summarized onto a live kanban — this IS the "可视化" centerpiece
- Local qodercli, no cloud dependency; fixture mode for always-working demos

**StepFun judges**:
- StepFun powers the full voice stack: stepaudio-2.5-realtime for CS + step-3.7-flash for dispatch brain
- Reliable text tool-calling (not realtime S2S tool calls — we decoupled that based on empirical testing)
- Pipecat-cascaded design: STT → text LLM + tools → TTS

**Viaim judges**:
- Viaim headset SDK enables the always-on earphone experience
- Voice-first means no screen needed — cycling, walking, driving
- The headset is the interface; Coding Vibe is the brain

---

## 7. Notion Product Diagram Insights (2026-07-25)

Reference images from the project's Notion documentation (downloaded to `docs/notion-images/`) reveal the actual product architecture and inform landing page visuals:

### Architecture Overview (`parent_9d34115b2a.png`, 2174x1050)
Shows the complete system flow: voice input at left, processing pipeline through CS/LLM/Qoder, kanban board on right, callback loop back to user. This is the definitive architecture reference. Used as the hero architecture image on the landing page (`docs/img/arch-overview.png`).

### OpenOPC Kanban UI (`tracks_7303f215e4.png`, 1856x620)
Real OpenOPC-style kanban board with 4 columns (Backlog, Running, Needs-Approval, Done), each populated with agent task cards. This is what the `coding-vibe` company board looks like in production. Used on the landing page as the primary screenshot (`docs/img/openopc-kanban.png`).

### Qoder Backend Architecture (`tracks_4c9a46e32e.png`, 941x298)
Qoder-specific backend diagram showing CEO-to-role-team fan-out pattern. Confirms the multi-agent orchestration model. Used on the landing page to explain the backend (`docs/img/qoder-backend.png`).

### Viaim SDK Integration (`tracks_8b371344ab.png`, 934x302)
Viaim SDK architecture showing the earphone-to-voice-pipeline integration. Used on the landing page to explain hardware/voice input (`docs/img/viaim-sdk.png`).

### Always-On Concept (`tracks_ffae0f9c71.png`, 512x464)
Square diagram illustrating the "always-on" coding companion concept — cycling, walking, driving scenarios. Used on the landing page to show the mobility use case (`docs/img/always-on.png`).

### Landing page integration
All five images are resized and optimized in `docs/img/` and embedded in `docs/landing.html` under a new "See It In Action" section with expandable lightbox. The SVG architecture diagram remains for conceptual clarity; the screenshots add credibility by showing real product UI.
