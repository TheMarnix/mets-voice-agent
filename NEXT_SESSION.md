# Next Session — OpenClaw Integration

## Where we are

Voice pipeline is working end-to-end on localhost:
- `server.py` — FastAPI, `/audio` WS (PCM16 in/out), `/events` WS (state stream)
- `pipeline.py` — VoicePipeline class, facts store, history compaction, pending-result delivery
- `static/index.html` — browser UI, circular mic button, diagnostic strip, Inter font
- `voice_agent.py` — standalone PyAudio version (kept separate, still works)

Read `BUILDLOG.md` and `STEPS.md` for full context.

## What we're building next

**Step 3 — OpenClaw task dispatch.**

Same pattern as `[SEARCH: query]`. When Haiku emits `[TASK: action]`, the pipeline:
1. Says a bridge phrase ("On it, I'll handle that.")
2. POSTs to OpenClaw `sessions.send` on `http://localhost:18789`
3. Emits `delegating` state to dashboard
4. Polls or subscribes for result
5. Narrates result back when it lands

## OpenClaw API surface (confirm before building)

OpenClaw runs on the Pi at port 18789. Check the actual API:
```bash
curl http://localhost:18789/
curl http://localhost:18789/sessions
```

The expected call pattern (verify against actual API):
```
POST /sessions/{session_id}/send
{ "message": "..." }
```

`OPENCLAW_URL` should be an env var defaulting to `http://localhost:18789`.

## Files to touch

- `pipeline.py` — add `[TASK: ...]` detection alongside `[SEARCH: ...]`, add `_dispatch_task()` method, add `OPENCLAW_URL` constant
- `static/index.html` — handle `delegating` state event (new state: indigo? teal?), show task in feed
- `STEPS.md` — mark Step 3 in progress

## System prompt change needed

Add to `SYSTEM_BASE` in `pipeline.py`:
> "If the user asks you to DO something that requires an external action (check calendar, read email, look at GitHub, set a reminder, send a message), output ONLY [TASK: describe the action clearly] — nothing else."

## Key question to resolve first

Does OpenClaw need a persistent session ID, or does it create one per message?
If persistent: create session on pipeline startup, reuse it.
If per-message: simpler, just POST each task independently.

Check with: `curl -X POST http://localhost:18789/sessions` or read OpenClaw docs.

## Deferred

- Pi deploy (Step 4) — after OpenClaw works on laptop
- HTTPS / mkcert for iPhone access over local WiFi
- ElevenLabs voice swap evaluation
