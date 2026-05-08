# Voice-First Personal AI Agent — Project Synthesis
> Living document. Start of a journey. Last updated: May 2026.

---

## Vision

Build a voice-native, agentic AI system that allows hands-free, always-on interaction with a capable, opinionated AI agent. The system should listen, push back, plan, take actions, remember, and improve over time — without requiring screen interaction. Built first for personal use, then open-sourced and presented as a portfolio/showcase project.

---

## Core Problem Being Solved

Existing voice AI interfaces (including current Claude voice) are too shallow:
- Context is lost between sessions
- No structured thinking or deep reasoning behind responses
- No agentic capability (can't actually do things)
- Too passive — no pushback, no real planning partner dynamic
- No memory that compounds over time

The goal is to fix all of this in a self-built stack.

---

## The Core Loop

```
[iPhone Mic]
    ↓
[Whisper STT — Speech to Text]
    ↓
[iOS App — lightweight client]
    ↓
[Raspberry Pi Backend — Agent Orchestrator]
    ↓
[Question Router → Sub-Agents]
    ↓
[Open Router — Model API layer]
    ↓
[TTS Response back to iPhone]
    ↓
[iPhone Dashboard — live agent activity view]
```

---

## Stack Decisions (Confirmed)

| Layer | Tool / Service | Notes |
|---|---|---|
| STT | Whisper (OpenAI) | Already familiar, proven on desktop |
| TTS | ElevenLabs or system TTS | Needs to be natural-sounding |
| Model Access | Open Router | API keys only, no local model hosting |
| Agent Framework | OpenClaw | Core agentic layer, to be hosted on Raspberry Pi |
| Orchestration | LangChain | Manages routing, sub-agents, tool calls |
| Realtime Database | Convex | Real-time sync between agent backend and iPhone dashboard |
| Memory | To be decided (see open questions) | Must persist and improve over time |
| Google Integration | Gmail, Google Calendar, Google Docs | Full Google ecosystem via API |
| Hardware | 2x Raspberry Pi 4 (4GB) | Backend host + potential redundancy |
| iOS Client | Custom-built Swift / React Native app | Voice input, TTS output, dashboard |

---

## Agent Architecture (Draft)

### Question Routing
One lightweight, fast model reads every incoming voice input and categorises it before anything else runs. Routing categories (draft):
- **Brainstorm / Ideation** → Creative reasoning model
- **Planning / Task breakdown** → Structured thinking model
- **Research query** → Research sub-agent (web-enabled)
- **Action / Integration** → Tool-use agent (Calendar, Gmail, Docs)
- **Memory recall** → Vector store query

### Parallel Processing (Desired)
When a complex question comes in, two things happen simultaneously:
1. A fast model begins formulating a response and narrating its reasoning ("Here's what I'm thinking, and here's what I've just sent off to research...")
2. A research or planning sub-agent spins up in the background

The user hears a live, conversational response while deeper work happens in parallel.

### Orchestration Considerations
- **Single orchestrator model** (e.g. one capable model like Claude Sonnet via Open Router that handles routing logic and delegates) vs. a dedicated lightweight router model
- **PocketFlow / similar minimal orchestration** worth exploring as an alternative to full LangChain if overhead becomes a concern
- LangChain remains the default starting point given flexibility and ecosystem

---

## Memory & Learning

This is a critical and still-open aspect of the project. Goals:

- Agent remembers past conversations, ideas, and plans
- Improves responses over time based on interaction patterns
- Connects new ideas back to previously discussed ones
- Potentially integrates with a tool like **Supermemory** for knowledge capture

Options to explore:
- **Vector store** (e.g. Chroma, Pinecone) for semantic memory retrieval
- **Convex** as the real-time persistent layer for session state and structured memory
- LangChain memory modules as a starting point
- Fine-tuning (longer-term, lower priority)

---

## Convex (Real-Time Database)

Introduced as an important layer for:
- Real-time sync between Raspberry Pi backend and iPhone dashboard
- Persisting agent state, task queues, and memory across sessions
- Powering the live dashboard (what is the agent doing right now?)

Convex's reactive, real-time nature makes it well-suited for showing live agent activity without polling.

---

## iPhone Dashboard (Desired)

A lightweight companion view that shows:
- Current agent status (thinking / researching / acting)
- Active sub-tasks and their progress
- Recent memory or context being referenced
- Completed actions (calendar events created, docs written, etc.)

This is both a functional tool and a key demo asset for the presentation.

---

## Google Ecosystem Integrations

All via API keys:
- **Google Calendar** — create, read, update events via voice
- **Gmail** — read summaries, draft and send emails
- **Google Docs** — create documents, append notes, write structured outputs

---

## Presentation Context

- **Audience**: Startup founders, reasonably AI-literate but not deeply technical
- **Format**: 15-minute slot
- **Tone**: Technically credible but accessible
- **Angle**: Showing the *building process* as much as the final result — decisions made, layers added, capabilities unlocked
- **Documentation**: Build logs, architecture diagrams, and possibly video captures of the agent in action will support the narrative
- **Key message**: This is what's possible when you layer voice I/O over a properly architected agentic system — and here's how I built it in a week

---

## Open Questions (Must Resolve)

1. **OpenClaw specifics** — Confirm licensing, API surface, and constraints around wrapping voice I/O on top of it. Does it support the routing architecture described?
2. **Memory architecture** — What combination of Convex + vector store + LangChain memory gives the best results without over-engineering?
3. **Orchestration model choice** — Single capable orchestrator vs. dedicated lightweight router. What's the latency / cost tradeoff?
4. **TTS quality** — ElevenLabs vs alternatives. What makes responses feel natural and engaging rather than robotic?
5. **Raspberry Pi constraints** — 4GB Pi 4s running LangChain + Convex client + OpenClaw. What offloads to cloud to stay performant?
6. **iOS app** — Swift native vs React Native. What's the fastest path to a working voice client with dashboard?
7. **Supermemory integration** — How does this fit with the vector store and Convex layers? Is it a replacement or a complement?

---

## What Makes This Novel

- Full hands-free voice loop with genuine agentic depth (not just Q&A)
- Pushback and active planning partner behaviour, not passive assistant
- Live agent activity dashboard — transparency into what the system is doing
- Persistent, compounding memory that improves over time
- Runs on accessible hardware (Raspberry Pi) with API-key-only architecture
- Built by one person in approximately one week — demonstrating speed of modern AI-assisted development

---

## Next Steps

- [ ] Research OpenClaw architecture and hosting on Raspberry Pi
- [ ] Evaluate Convex for real-time agent state layer
- [ ] Prototype the question router (fast model + category taxonomy)
- [ ] Sketch iOS app wireframe — voice input + dashboard view
- [ ] Define memory architecture in detail
- [ ] Set up Open Router account and test model routing
- [ ] Decide on TTS provider and test voice quality
- [ ] Begin build log / documentation for presentation narrative

---

*This document is the first stone. Each session should update and extend it as decisions are made and components are built.*
