# MeTs Build Steps

> Execution roadmap. Pick up from here if context is lost.
> Current state: voice_agent.py works end-to-end on laptop (STT → LLM → TTS, interruption, search, history). Missing: web interface, dashboard, task delegation.

---

## Step 1 — FastAPI refactor ✅ IN PROGRESS

**What:** Turn `voice_agent.py` into a server. Voice logic becomes a module. FastAPI exposes two WebSocket endpoints.

**Endpoints:**
- `WS /audio` — browser sends raw PCM16 binary frames (AudioWorklet), server streams TTS audio back as binary frames
- `WS /events` — server pushes state events (listening / thinking / speaking / searching / delegating) for the dashboard

**Entry point:** `server.py` (new file). `voice_agent.py` split into `pipeline.py` (core logic) + `server.py` (FastAPI wrapper).

**Test:** `uvicorn server:app --reload` → open browser → confirm WebSocket connects → confirm mic audio flows to Deepgram → confirm TTS audio plays back in browser.

**Files touched:** `server.py` (new), `pipeline.py` (new, extracted from voice_agent.py), `static/` (new dir for HTML client)

---

## Step 2 — Dashboard + browser audio client

**What:** Single HTML page served by FastAPI. Two functions: (1) mic button triggers /audio WebSocket, plays TTS back via AudioContext; (2) live state strip shows what MeTs is doing right now.

**Audio capture:** AudioWorklet (not MediaRecorder). Float32 → Int16 conversion in worklet. Send as binary ArrayBuffer over WebSocket. Receive TTS as binary ArrayBuffer, play via AudioContext ring buffer.

**Dashboard:** Subscribes to /events WebSocket. Shows: LISTENING / THINKING / SPEAKING / SEARCHING / DELEGATING. This is the demo differentiator — transparency layer no commercial product shows.

**Test:** Open `http://localhost:8000` on laptop browser → grant mic → speak → hear response → see state update in dashboard.

**Files:** `static/index.html`, `static/worklet.js`

---

## Step 3 — OpenClaw task dispatch

**What:** `[TASK: ...]` pattern alongside `[SEARCH: ...]`. When Haiku emits `[TASK: action]`, voice layer says "on it" and fires a POST to OpenClaw `sessions.send` on port 18789. Polls or subscribes for result. Narrates result back when it lands.

**OpenClaw host:** `OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://localhost:18789")` — swap to Pi IP at deploy time, zero other changes.

**Memory ownership:** Voice layer is stateless, forwards full utterance to OpenClaw. OpenClaw builds its own session context. No duplication.

**Test:** Ask MeTs something that requires a task (e.g. "check my GitHub notifications") → hear "on it" → hear result narrated back → confirm OpenClaw session log shows the task.

**Files:** `pipeline.py` (add task dispatch alongside search dispatch)

---

## Step 4 — Pi deploy

**What:** Move everything to Pi. Pi serves FastAPI on local network. iPhone Safari opens the dashboard page and uses it as the interface.

**Steps:**
1. `scp` repo to Pi
2. `pip install -r requirements.txt` on Pi (no PyAudio needed)
3. Set up systemd service for `uvicorn server:app --host 0.0.0.0 --port 8000`
4. Solve HTTPS: `mkcert` on Pi + install root cert on iPhone, OR Cloudflare tunnel
5. Open `https://<pi-ip>:8000` on iPhone — grant mic — test

**OpenClaw:** already running as systemd service on Pi (port 18789). `OPENCLAW_URL=http://localhost:18789` in `.env`. No changes.

**Gotcha:** getUserMedia (mic) requires HTTPS or localhost. iPhone accessing Pi over local WiFi is neither without a cert. Don't skip this — mic will silently fail.

---

## Deferred

- ElevenLabs voice swap (Day 3 evaluation — only if Cartesia quality matters for demo)
- Multiple Google integrations — Calendar probably most demo-friendly
- Native iOS app (v2)
- Cross-session memory beyond what's already in `~/.mets_history.json`
