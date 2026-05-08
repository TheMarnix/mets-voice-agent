# MeTs — Voice-First Personal AI Agent

> Hands-free, voice-native, async agentic delegation. Runs on a Raspberry Pi.
> Built publicly in 4 days as a portfolio + presentation project.

## What this is

You speak. An agent picks up the task, runs in the background, narrates that it's working, and talks back when done. A live web dashboard shows what it's doing in real time. Not a chatbot — a productivity layer.

**Canonical use case:** On a morning walk, say "synthesize my last week of GitHub commits into a 5-minute presentation recap." The agent dispatches, the dashboard lights up, and a finished narration is waiting when you sit down.

## Stack (locked Day 0)

| Layer | Choice |
|---|---|
| Voice I/O | OpenClaw (iOS Canvas, native voice) |
| STT | Whisper (via OpenClaw or OpenRouter) |
| TTS | ElevenLabs |
| Models | OpenRouter (Claude / GPT / Gemini routed by task) |
| Orchestration | Custom thin layer on top of OpenClaw |
| Persistence | SQLite |
| Dashboard | FastAPI + WebSocket, web UI |
| Hardware | Raspberry Pi 4 (4GB) |

**Explicitly not used (and why):** LangChain (over-abstracted), Convex (overkill for solo persistence), native iOS app (web on Safari is enough for v1), Supermemory / Pinecone (premature).

**Under evaluation:** Paperclip — could replace the custom dashboard layer with multi-agent orchestration out of the box. Day 3 decision.

## Architecture

See [`ARCHITECTURE.md`](./ARCHITECTURE.md). Diagram is rebuilt daily as decisions evolve.

## Build log

See [`BUILDLOG.md`](./BUILDLOG.md). Dated entries, decisions + reasoning, written daily. This is the source material for the presentation.

## Repo layout

```
/                  voice_agent_project.md  — original synthesis
/ARCHITECTURE.md   live architecture diagram (mermaid + excalidraw)
/BUILDLOG.md       daily build journal
/CLAUDE.md         agent instructions for Claude Code sessions
/src               (coming Day 1)
/dashboard         (coming Day 2-3)
```

## Why publicly

The whole point of the project is the *speed of a single person with the right tools in 2026*. The build log is the artifact.
