# CLAUDE.md — Agent instructions for this repo

## What this project is

MeTs is a voice-first personal AI agent built on Raspberry Pi. 4-day build for a startup-founder presentation. See `README.md` and `voice_agent_project.md` for full context.

## How to work in this repo

- **Read `BUILDLOG.md` first.** It's the most current state of the project — more current than the original synthesis doc.
- **Update `BUILDLOG.md` at the end of every working session.** Date-stamped. Honest about what broke. This is the presentation source material, not a marketing page.
- **Update `ARCHITECTURE.md` when the diagram changes.** Bump the version, add a row to the decision log.
- **Do not push commits.** The user commits manually. Stage and prepare; never `git push`.
- **Lean output.** Short dense responses. No long explanations unless asked.

## Stack constraints

- OpenClaw is the gateway. Don't introduce LangChain, Convex, or other heavy frameworks.
- SQLite for persistence. Flat JSON acceptable for prototypes.
- Web dashboard, not native iOS. FastAPI + WebSocket.
- OpenRouter for model access. ElevenLabs for TTS. Whisper for STT.

## What's deferred

- Paperclip orchestration (Day 3 evaluation)
- Native iOS app (v2)
- Cross-session memory beyond OpenClaw built-ins (Day 3)
- Multiple Google integrations — pick one (probably GitHub first, Calendar second)

## Tone

This is a personal portfolio project. Move fast, document honestly, prefer working over perfect.
