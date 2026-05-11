# Build Log

> Daily journal. Decisions, surprises, blockers, fixes. Written same-day while fresh.
> This is the presentation source material — not a polished doc.

---

## Day 0 — 2026-05-08 — Scoping & decisions

**Status:** Pre-build. Stack locked. Repo initialised.

**Decisions made today:**
- **Dropped LangChain.** OpenClaw is a complete product, not a framework. Wiring LangChain on top duplicates routing/sessions/memory that OpenClaw already provides. Net negative on a 3-day build.
- **Dropped Convex.** SQLite + WebSocket covers persistence + dashboard sync for one user. Convex shines at multi-client real-time sync, which isn't the use case here.
- **No native iOS app for v1.** Web dashboard served from the Pi, opened on iPhone Safari. Saves 1.5 days minimum. Native app is a v2 problem.
- **Pi-first, not laptop-first.** Pi is already SSH'd and configured. Running on it from Day 1 means no laptop→Pi port pain on Day 3.
- **Paperclip flagged but deferred.** Could replace the custom dashboard with multi-agent orchestration. Re-evaluate Day 3 once the voice loop is stable.

**Differentiators (locked):**
- Self-hosted on accessible hardware (the Pi is a physical prop in the demo room)
- Live activity dashboard — transparency layer no commercial product has
- "Pushback" personality — opinionated planning partner, not passive assistant
- Async delegation pattern — fire and forget, narrated mid-flight

**Patterns to implement (parked for Day 2-3):**
- **Fast / slow dual-agent routing.** Lightweight model produces an immediate conversational response while a heavier model runs deep research in parallel. User hears something fast, then gets the deep answer when it lands. Architecturally this is two parallel API calls + a state merge.

**What I'm not doing:**
- Polishing the voice — quality is Day 3
- Building integrations — pick one (likely GitHub) on Day 3
- Memory beyond OpenClaw's built-in sessions until Day 3

---

## Day 1 — 2026-05-08 — Pi config, GCP TTS, repo wired

**Status:** Pi SSH'd and configured. Google Cloud TTS credentialed. OpenClaw setup in progress.

**What I built:**
- Swapped ElevenLabs → Google Cloud TTS (Neural2). Cost: ~$0.016/1k chars vs $0.30/1k. Free tier covers entire build.
- GCP project created, Text-to-Speech API enabled, service account + JSON key deployed to Pi at `/home/marnixf/mets-credentials.json`
- `GOOGLE_APPLICATION_CREDENTIALS` set in `/home/marnixf/.bashrc`
- Claude Code skills added: `/push` (outputs copy-paste git commands), `/buildlog` (prompts for session notes, writes entry)
- Fixed README.md merge conflict left over from GitHub repo init collision

**What broke / what I learned:**
- scp lands in `/home/marnixf/` not `/root/` — obvious in hindsight, bit me because I was SSHed as root
- `.bashrc` as root resolves to `/root/.bashrc`, not the user homedir — set export manually for the session, then wrote to the correct file
- GitHub auto-creates commits on repo init — pulls need `--allow-unrelated-histories --no-rebase` on first sync

**Decisions:**
- Google Cloud TTS locked in for v1. ElevenLabs stays as a Day 3 swap *only if* voice quality matters for the live demo.
- Build compressed from 4 days to 3 days.

**In progress:**
- OpenClaw install on Pi — Node version TBC, first text round-trip not yet confirmed

---

## Day 2 — 2026-05-10 — OpenClaw on Pi, Telegram live, latency problem surfaced

**Status:** IN PROGRESS. OpenClaw gateway running as systemd service. Telegram paired and responding. Latency is the active problem.

**What I built:**
- Node 24 installed via nvm — Pi OS ships Node 18 which is too old; openclaw requires 22.16+ minimum
- systemd service at `/etc/systemd/system/openclaw.service` — required absolute nvm binary paths in both `ExecStart` and `Environment=PATH=...`; nvm is a shell function, not available in service context
- Correct headless start command is `openclaw gateway` — bare `openclaw` launches Crestodian interactive TUI which immediately exits without a TTY
- Model set to `openrouter/google/gemini-2.5-flash` via OpenRouter — best latency/quality ratio for a voice agent at ~$0.15/1M tokens
- Hooks enabled during quickstart: boot-md, session-memory, command-logger, compaction-notifier
- Search provider: Brave (1,000 free queries/month, OpenClaw's first auto-detect priority)
- Telegram channel configured — BotFather bot token given to OpenClaw, account paired via `openclaw pairing approve telegram <code>`
- Bot (@MeTsClawbot) live and responding on Telegram

**What broke / what I learned:**
- Skills install failed — OpenClaw's quickstart skill installer expects brew, which isn't on Pi OS. Skills need manual apt/npm install. Deferred.
- `openclaw run "hello"` is not a valid command — doesn't exist. `openclaw gateway` starts the server; you talk to it through the channel (Telegram), not the terminal.
- Ran two openclaw instances simultaneously — they conflict on port 18789 and a lock file. Only one gateway per machine.
- First systemd attempt: `ExecStart` pointed to `openclaw` binary but `node` wasn't in PATH → exit 127. Fixed by adding full nvm bin dir to `Environment=PATH=`.
- Second systemd attempt: bare `openclaw` command → Crestodian TUI exits immediately without TTY. Fixed by using `openclaw gateway`.
- Duplicate gateway on restart: old pid 17299 still running when new service started → "gateway already running" error. Fixed with `openclaw gateway stop` then `systemctl restart`.
- Latency: eventLoopDelayMax 71s, cpuRatio 1.3 during startup. Caused by: model prewarm (2.2s), Telegram polling interval, OpenRouter API round-trip, serial message queue. Pi CPU is fine at idle (0.3%) — the bottleneck is queue depth + network, not compute.
- Two messages sent back-to-back → both queued serially → 2+ min combined wait. Completely unworkable for voice.
- Security flag: `gateway.controlUi.allowInsecureAuth=true` in config — needs `openclaw security audit` before demo.
- Browser control sidecar starts automatically on port 18791 — not disabled yet, consuming RAM unnecessarily.

**Decisions:**
- `openrouter/auto` dropped in favour of explicit `openrouter/google/gemini-2.5-flash`. Auto is unpredictable on cost and can route to slow models.
- Sub-agent pattern confirmed viable within a single OpenClaw instance: fast main agent + browser-enabled researcher sub-agent spawned on demand. Two full instances conflict on port — not the right approach.
- **New architectural direction under evaluation:** thin fast-response orchestration layer sitting above OpenClaw. This layer receives voice input, gives an immediate spoken acknowledgement ("on it..."), then passes the task to OpenClaw for heavy execution. Solves the voice UX latency problem at the cost of added complexity. Open question: memory ownership — if this layer intercepts before OpenClaw, does OpenClaw still build session context from the conversation? Needs design resolution before building.

**Architecture resolved — voice pipeline stack locked (end of Day 2 session):**
- Two-layer design confirmed: **Response layer** (streaming, <2s, always-on) + **Working layer** (OpenClaw, async task execution, persistent memory).
- Memory ownership resolved: response layer is stateless, forwards full utterance to OpenClaw via WebSocket — OpenClaw builds session context as normal.
- Telegram dropped from voice loop entirely. OpenClaw receives tasks via WebSocket `sessions.send` on port 18789. Telegram stays as async mobile channel only.
- Web search disabled on OpenClaw main agent; sub-agents retain it.
- **STT: Deepgram** (Nova/Flux, streaming WebSocket) — chosen over Google STT for better real-time conversational feel, VAD, and interruption handling.
- **LLM: Claude Haiku 4.5** (Anthropic API direct, streaming) — chosen over Gemini Flash 2.5 for lower perceived latency, smoother token cadence, better short-form conversational pacing.
- **TTS: Cartesia Sonic** (streaming) — chosen over GCP TTS Neural2 despite higher cost; TTS identified as the least-solved layer in real-time voice, Cartesia currently leads on latency and interruption-friendly synthesis. GCP TTS remains fallback.
- Next session: build `voice_agent.py` — Deepgram STT → Haiku 4.5 → Cartesia TTS pipeline. No OpenClaw yet. Goal: talking to the AI and hearing it respond within ~2s.

**Voice pipeline built and working (Day 2 continued — 2026-05-11):**
- `voice_agent.py` written and running end-to-end on Mac: iPhone mic → Deepgram Flux → Haiku 4.5 → Cartesia Gavin voice → speakers
- Deepgram SDK was v7 (Fern-generated), completely different from assumed v3 — no `LiveOptions`, no `LiveTranscriptionEvents`. Correct API: `AsyncDeepgramClient`, `listen.v2.connect()` as async context manager, `send_media()`, `start_listening()`, events via `EventType.MESSAGE`
- Python 3.14 broke `isinstance(msg, ListenV2TurnInfo)` — SDK returns raw dicts, not typed objects. Fixed by normalising both cases in the message handler
- `audioop` removed in Python 3.13+ — replaced with manual `struct`-based RMS
- Cartesia `context_id` rejects dots — fixed by replacing `.` with `-` in float timestamp
- Stale `ANTHROPIC_API_KEY` in `~/.zshrc` overrode `.env` silently — found and deleted; `load_dotenv(override=True)` added as belt-and-suspenders
- Flux is a v2 model (`listen.v2.connect`), Nova is v1 — wrong API path caused HTTP 400
- Barge-in / interruption implemented: mic always live (no gate), `StartOfTurn` sets `asyncio.Event` which cancels in-flight LLM stream and TTS playback mid-chunk; queue drained to latest utterance only
- Speaker bleed caused false barge-ins on MacBook (mic picks up own speakers) — solved by switching input to iPhone Continuity Microphone (device index 0), grace period logic written then removed as unnecessary with physical mic separation
- Voice: Cartesia Gavin (`f4a3a8e4`) — casual male, good for conversational demo

**Interruption + latency fix (Day 2 continued):**
- Root cause of broken interruption found: sync `Anthropic` client blocked the entire asyncio event loop during token streaming — Deepgram `StartOfTurn` events could never fire mid-response. Fixed by switching to `AsyncAnthropic` with `async for token in stream.text_stream`
- `tts_speak` replaced 100ms polling with `asyncio.wait` racing `ws.recv()` against `interrupt.wait()` — interrupt response is now instant rather than up to 100ms delayed
- `spk.write()` moved to `run_in_executor` so PyAudio audio writes no longer block the event loop during playback
- `EagerEndOfTurn` added as primary LLM trigger alongside `EndOfTurn` — fires ~300ms earlier
- `TurnResumed` added as barge-in cancel trigger (covers false-silence case)
- `MIC_CHUNK` halved from 8000 to 4000 (500ms → 250ms) for faster Deepgram turn detection
- Speaker bleed / echo confirmed as MacBook hardware limitation — laptop mic picks up laptop speakers. Tested iPhone Continuity Mic and AirPods as inputs; settled on MacBook mic (fixed by name, not index) with system default output (swaps automatically when AirPods connect)
- Outstanding: in-session conversation history appears to not persist correctly — needs investigation next session

---

## Day 3 — 2026-05-11 — Memory fix, live search, STT comparison

**What I built:**
- Fixed conversation memory bug: when interrupted before any tokens, user message was appended to history with no assistant reply → two consecutive user messages → Anthropic API role violation. Fix: pop the dangling user message if `full_response` is empty on interrupt.
- Refactored `respond()` into `respond()` + `stream_response()` helper to allow reuse for post-search second LLM call.
- Live research via [SEARCH: query] pattern: system prompt tells Haiku to emit `[SEARCH: query]` alone when it needs live data. `respond()` detects the pattern after stream ends, fires Brave search, injects results, streams second Haiku call. Agent says "On it, looking that up." during the search gap.
- Cross-session history persistence: `load_history()` / `save_history()` read/write `~/.mets_history.json`. Last 40 messages (20 turns) kept. History loaded at startup, saved on clean Ctrl+C shutdown.
- Added `httpx` to requirements.txt for async Brave search HTTP calls.

**STT comparison — Deepgram vs Groq:**

| Provider | Model | Streaming WS? | Latency | Cost/min | Verdict |
|---|---|---|---|---|---|
| Deepgram | Flux | ✅ | ~260ms EOT | $0.0077 | **Use this** |
| Deepgram | Nova-2 | ✅ | ~1.5s | $0.0058 | Slower, cheaper |
| Groq | Whisper Large v3 Turbo | ❌ batch only | N/A | $0.00067 | Not viable |

Decision: stay on Deepgram Flux. Groq is batch file upload only — no streaming WebSocket. Nova-2 is ~6× slower to first word. Cost delta ($0.0077 vs $0.0058/min) is ~$0.13/hr — irrelevant for demo.

**What broke / what I learned:**
- Memory bug root cause: `history.append(user_msg)` fires before streaming starts, but interrupted-with-no-tokens leaves no assistant reply. Anthropic API requires strictly alternating roles — consecutive user messages silently corrupt context rather than raising a 400. Confirmed by code inspection; not yet live-tested.
- [SEARCH: ...] pattern won't trigger TTS sentence flush mid-stream (no sentence-ending punctuation) — whole token lands in `buf` after stream ends. Detection is clean, no premature speech.

**Two-layer memory system built and wired:**
- Rolling summary (`compact_history()`): background `asyncio.create_task()` after every turn. When history exceeds 10 turns, compresses oldest turns into a 4–6 sentence summary block, keeps last 6 verbatim. Summary prompt explicitly preserves numbers, decisions, specific facts. Triggers every ~4 turns after first compaction. Zero latency impact.
- Fact extraction (`extract_facts()`): background task after every completed turn. Single Haiku call reads `~/.mets_facts.json`, extracts anything persistently true from the exchange (preferences, location, name, communication style, standing decisions), merges, writes back. Injected into system prompt via `build_system_prompt()` every turn — agent knows user context without being re-told. Capped at 60 entries.
- Both fire-and-forget via `asyncio.create_task()`. One-turn lag on facts (turn N facts available at turn N+2) — unnoticeable.
- `~/.mets_facts.json` persists indefinitely. `~/.mets_history.json` saves recent turns on clean shutdown.

**Search result persistence fixed:**
- Raw search results now stored in the assistant's history entry alongside the spoken response. Follow-up questions ("convert that to Celsius") see the actual data — no re-search triggered.
- System prompt tightened: added "NOT already visible in the conversation" clause to prevent topic-matching false positives on search.

**Memory architecture decisions:**
- Third layer (behavioral rules — free-text interaction patterns, `~/.mets_style.md`) identified but deferred until voice pipeline is demo-stable.
- Real constraint on fact store is structure (flat key-value), not count. Personality needs behavioral rules, not more facts.
- Tag-based retrieval (inject only topic-relevant facts per turn) is the right next step if store grows large. No vector DB needed. Future problem.

**Architecture planning session (2026-05-11) — used AI to stress-test and lock the stack:**
- Voice agent is working and feels good. Problem identified: it's a local voice chat clone — no dashboard, no task delegation, not meaningfully different from Claude voice / ChatGPT voice yet.
- Researched how OpenAI and Google handle browser voice. Verdict: AudioWorklet + raw PCM16 binary WebSocket frames is the right pattern. Not MediaRecorder/Opus (buffers, wrong format). Not base64 JSON (33% bandwidth waste). Binary ArrayBuffer direct to server.
- Pi role clarified: Pi is a server, not an audio device. iPhone browser owns mic + speaker. Pi hosts FastAPI, voice pipeline, OpenClaw. No PyAudio on Pi.
- Latency target confirmed: STT ~260ms (Deepgram Flux), total voice-to-voice under 800ms. Already within budget.
- HTTPS / secure context issue flagged for Pi deploy: getUserMedia requires HTTPS or localhost. iPhone over local WiFi hits a non-localhost non-HTTPS URL — mic blocked. Fix when we get there: mkcert or Cloudflare tunnel. Deferred for now, single user prototype.
- OpenClaw host is a config constant. `localhost:18789` on laptop, Pi IP on deploy. Zero code changes to move environments.
- Build order locked: (1) FastAPI refactor — voice_agent.py becomes a server, /audio WS + /events WS. (2) Dashboard page — live agent state, iPhone-accessible. (3) OpenClaw dispatch — [TASK: ...] pattern, async task delegation. (4) Pi deploy.
- AI used heavily in this session for architecture review, latency research, and stack validation. Decisions are informed, not cargo-culted.

---

<!-- Template for future entries:

## Day N — YYYY-MM-DD — One-line summary

**Status:**

**What I built:**

**What broke / what I learned:**

**Decisions:**

-->
