# Build Log

> Daily journal. Decisions, surprises, blockers, fixes. Written same-day while fresh.
> This is the presentation source material — not a polished doc.

---

## Day 0 — 2026-05-08 — Scoping & decisions

**Status:** Pre-build. Stack locked. Repo initialised.

**Decisions made today:**
- **Dropped LangChain.** OpenClaw is a complete product, not a framework. Wiring LangChain on top duplicates routing/sessions/memory that OpenClaw already provides. Net negative on a 4-day build.
- **Dropped Convex.** SQLite + WebSocket covers persistence + dashboard sync for one user. Convex shines at multi-client real-time sync, which isn't the use case here.
- **No native iOS app for v1.** Web dashboard served from the Pi, opened on iPhone Safari. Saves 1.5 days minimum. Native app is a v2 problem.
- **Pi-first, not laptop-first.** Pi is already SSH'd and configured. Running on it from Day 1 means no laptop→Pi port pain on Day 4.
- **Paperclip flagged but deferred.** Could replace the custom dashboard with multi-agent orchestration. Re-evaluate Day 3 once the voice loop is stable.

**Differentiators (locked):**
- Self-hosted on accessible hardware (the Pi is a physical prop in the demo room)
- Live activity dashboard — transparency layer no commercial product has
- "Pushback" personality — opinionated planning partner, not passive assistant
- Async delegation pattern — fire and forget, narrated mid-flight

**Patterns to implement (parked for Day 2-3):**
- **Fast / slow dual-agent routing.** Lightweight model produces an immediate conversational response while a heavier model runs deep research in parallel. User hears something fast, then gets the deep answer when it lands. Architecturally this is two parallel API calls + a state merge.

**What I'm not doing:**
- Polishing the voice — quality is Day 4
- Building integrations — pick one (likely GitHub) on Day 3
- Memory beyond OpenClaw's built-in sessions until Day 3

**Tomorrow (Day 1):**
- OpenClaw running on the Pi via SSH
- Voice round-trip working end-to-end (mic → model → speech back)
- Architecture diagram v0 in Obsidian / Excalidraw
- First commit, first build log update with what actually broke

---

<!-- Template for future entries:

## Day N — YYYY-MM-DD — One-line summary

**Status:**

**What I built:**

**What broke / what I learned:**

**Decisions:**

**Tomorrow:**

-->
