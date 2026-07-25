# Test-Feedback Loop Targets — Coding Vibe

## Test Products

| # | Product | URL | Core Flow |
|---|---------|-----|-----------|
| 1 | Landing Page | http://localhost:5091/docs/landing.html | Scroll full page, click all links, open lightbox images, check mobile responsive |
| 2 | Project Index | http://localhost:5091/ | Click all navigation links, verify all demo links work |
| 3 | Company Kanban | http://localhost:5091/company | Board loads, columns visible, card rendering |
| 4 | Voice Client | http://localhost:7860/ | Page loads, Call button works, mic permission flow |

## Personas

| Persona | Identity | Language | Device | Priority |
|---------|----------|----------|--------|----------|
| **Judge** | AdventureX judge evaluating for Qoder/StepFun track | EN primary | Mac laptop | P0 |
| **Student** | Chinese student hacker, mobile-native | Mixed ZH/EN | Phone + laptop | P0 |

## Core Journeys (per persona)

### Journey A — First impression (Judge)
1. Open landing page → scroll hero → read tagline
2. Scroll to architecture → verify diagram renders
3. Click "See It In Action" → open lightbox images → close
4. Read comparison table → verify claims
5. Scroll to "Try It" → click links → verify they work
6. Open GitHub link → verify it exists

### Journey B — Live demo (Judge)
1. Open voice page → verify UI loads
2. Click Call → verify mic permission prompt
3. Verify status changes from "idle" to "connecting"
4. Speak a test task → verify transcript appears
5. Check kanban for task card

### Journey C — Quick explore (Student)
1. Open index page → scan links
2. Check voice demo → try calling
3. Check kanban → verify visual layout
4. Open landing page on phone → verify mobile layout
5. Check GitHub → verify README

## Last Run
2026-07-25 — initial run
