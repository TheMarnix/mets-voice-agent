"""
MeTs voice pipeline — server mode.
One VoicePipeline instance per browser WebSocket session.

Audio in:  binary PCM16 frames from browser AudioWorklet → Deepgram
Audio out: binary PCM16 frames from Cartesia → browser
"""

import asyncio
import base64
import json
import os
import random
import re
import sys
from pathlib import Path

import httpx
import websockets
from anthropic import AsyncAnthropic
from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.listen.v2.types import ListenV2TurnInfo
from dotenv import load_dotenv
from fastapi import WebSocket

load_dotenv(Path(__file__).parent / ".env", override=True)

DEEPGRAM_API_KEY  = os.environ["DEEPGRAM_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CARTESIA_API_KEY  = os.environ["CARTESIA_API_KEY"]
BRAVE_API_KEY     = os.environ.get("BRAVE_API_KEY", "")

MIC_RATE  = 16000
TTS_RATE  = 22050

HAIKU_MODEL     = "claude-haiku-4-5"
CARTESIA_VOICE  = "f4a3a8e4-694c-4c45-9ca0-27caf97901b5"  # Gavin
CARTESIA_MODEL  = "sonic-3.5"
CARTESIA_WS_URL = "wss://api.cartesia.ai/tts/websocket?cartesia_version=2026-03-01"

HISTORY_FILE         = Path.home() / ".mets_history.json"
FACTS_FILE           = Path.home() / ".mets_facts.json"
COMPACTION_THRESHOLD = 10
KEEP_RECENT_TURNS    = 6
MAX_FACTS            = 30

SYSTEM_BASE = (
    "You are MeTs, a voice AI assistant on a Raspberry Pi. "
    "You have persistent memory — use it naturally. Never announce it. "
    "Never say 'picking up from last session', 'I remember you said', or anything similar. "
    "Just know what you know and respond accordingly. "
    "Respond in 1–3 short sentences. "
    "Plain spoken English only — no markdown, bullet points, or lists. "
    "If you need live or current information that is NOT already in this conversation "
    "(weather, news, prices, real-time data), output ONLY [SEARCH: your query] — "
    "nothing before it, nothing after it, not even punctuation. "
    "If search results already in the conversation don't fully answer the user's current question, "
    "emit [SEARCH: better query] to get what's needed. "
    "For anything the conversation already covers completely, answer directly without searching again."
)

SEARCH_BRIDGES = [
    "Let me get that for you.",
    "Give me a second.",
    "Looking that up now.",
    "Just a moment.",
    "Let me check that.",
    "On it.",
]

anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


# ── Persistence ────────────────────────────────────────────────────────────────

def load_history() -> list[dict]:
    try:
        data = json.loads(HISTORY_FILE.read_text())
        msgs = data[-(KEEP_RECENT_TURNS * 2):]
        print(f"[Memory] Loaded {len(msgs) // 2} prior turns.")
        return msgs
    except Exception:
        return []


def save_history(history: list[dict]) -> None:
    try:
        HISTORY_FILE.write_text(json.dumps(history[-(KEEP_RECENT_TURNS * 2):]))
    except Exception:
        pass


def load_facts() -> dict:
    try:
        return json.loads(FACTS_FILE.read_text())
    except Exception:
        return {}


def save_facts(facts_store: dict) -> None:
    try:
        FACTS_FILE.write_text(json.dumps(facts_store, indent=2))
    except Exception:
        pass


# ── Sentence chunker ───────────────────────────────────────────────────────────

def flush_sentences(buf: str) -> tuple[list[str], str]:
    parts = re.split(r"(?<=[.!?])\s+", buf)
    if len(parts) == 1:
        if re.search(r"[.!?]\s*$", buf):
            return [buf.strip()], ""
        return [], buf
    return [p for p in parts[:-1] if p.strip()], parts[-1]


# ── Brave search ───────────────────────────────────────────────────────────────

async def brave_search(query: str) -> str:
    if not BRAVE_API_KEY:
        return "Web search is not configured (no BRAVE_API_KEY)."
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 3},
                headers={
                    "X-Subscription-Token": BRAVE_API_KEY,
                    "Accept": "application/json",
                },
            )
            r.raise_for_status()
            data = r.json()
        results = data.get("web", {}).get("results", [])
        snippets = [f"{res['title']}: {res.get('description', '')}" for res in results[:3]]
        return " | ".join(snippets) if snippets else "No results found."
    except Exception as e:
        return f"Search failed: {e}"


# ── Pipeline ───────────────────────────────────────────────────────────────────

class VoicePipeline:
    def __init__(self, event_bus=None):
        self.history: list[dict]         = []
        self.facts_store: dict           = {}
        self.pending_result: dict | None = None
        self.is_responding               = False
        self.interrupt                   = asyncio.Event()
        self.event_bus                   = event_bus
        self.tts_active                  = False
        self.tts_immune_until            = 0.0

    async def _emit(self, state: str, detail: str = "") -> None:
        if self.event_bus:
            await self.event_bus.publish({"state": state, "detail": detail})

    def _build_system_prompt(self) -> str:
        if not self.facts_store:
            return SYSTEM_BASE
        lines = "\n".join(f"- {k}: {v}" for k, v in list(self.facts_store.items())[:MAX_FACTS])
        return (
            SYSTEM_BASE
            + "\n\nBackground context about this user (use only if directly relevant to what they're asking now):\n"
            + lines
        )

    async def _extract_facts(self, utterance: str, response: str) -> None:
        try:
            result = await anthropic_client.messages.create(
                model=HAIKU_MODEL, max_tokens=400,
                messages=[{"role": "user", "content": (
                    "You maintain a persistent memory store for a personal voice AI assistant.\n\n"
                    f"Current memory: {json.dumps(self.facts_store)}\n\n"
                    f"New exchange:\nUser: {utterance}\nAssistant: {response}\n\n"
                    "Extract facts about WHO the user is — not what they asked about. "
                    "Include: name, location, language/communication preferences, "
                    "standing decisions, and things they consistently care about. "
                    "Do NOT store: search topics, recent questions, current events discussed, "
                    "or anything specific to this conversation. "
                    "Update conflicting entries. "
                    f"Keep total under {MAX_FACTS} entries. "
                    "Return only the updated JSON object, or unchanged if nothing new."
                )}],
            )
            updated = json.loads(result.content[0].text)
            if updated != self.facts_store:
                self.facts_store = updated
                save_facts(self.facts_store)
                print(f"[Memory] Facts updated → {len(self.facts_store)} entries")
                await self._emit("facts", str(len(self.facts_store)))
        except Exception as e:
            print(f"[Memory] Fact extraction failed: {e}", file=sys.stderr)

    async def _compact_history(self) -> None:
        if len(self.history) // 2 <= COMPACTION_THRESHOLD:
            return
        keep   = KEEP_RECENT_TURNS * 2
        old    = self.history[:-keep]
        recent = self.history[-keep:]
        text   = "\n".join(
            f"{'User' if m['role']=='user' else 'MeTs'}: {m['content'][:300]}" for m in old
        )
        try:
            result = await anthropic_client.messages.create(
                model=HAIKU_MODEL, max_tokens=250,
                messages=[{"role": "user", "content": (
                    "Summarise this conversation in 4–6 sentences. Preserve specific facts, "
                    "numbers, decisions, and preferences. Be concrete.\n\n" + text
                )}],
            )
            summary = result.content[0].text.strip()
            self.history = [
                {"role": "user",      "content": f"[Earlier conversation: {summary}]"},
                {"role": "assistant", "content": "Understood, I have that context."},
            ] + recent
            print(f"[Memory] Compacted {len(old)} messages → summary block.")
        except Exception as e:
            print(f"[Memory] Compaction failed: {e}", file=sys.stderr)

    async def _queue_pending_result(self, query: str, raw_results: str) -> None:
        try:
            r = await anthropic_client.messages.create(
                model=HAIKU_MODEL, max_tokens=80,
                messages=[{"role": "user", "content":
                    f"In one short spoken sentence (no markdown), summarise the search result "
                    f"for '{query}':\n{raw_results[:600]}"}],
            )
            spoken = r.content[0].text.strip()
        except Exception:
            spoken = f"I did find results for {query} but couldn't summarise them."
        self.pending_result = {"query": query, "spoken": spoken, "raw": raw_results}
        print(f"[Search] Queued pending result for '{query}'")

    async def _tts_speak(self, ws_cartesia, ws_browser: WebSocket, text: str) -> bool:
        """Stream one sentence from Cartesia → browser. Returns False if interrupted."""
        text = text.strip()
        if not text:
            return True

        loop = asyncio.get_running_loop()
        self.tts_active = True
        ctx = f"mets-{loop.time():.3f}".replace(".", "-")
        await ws_cartesia.send(json.dumps({
            "model_id": CARTESIA_MODEL,
            "transcript": text,
            "voice": {"mode": "id", "id": CARTESIA_VOICE},
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": TTS_RATE,
            },
            "context_id": ctx,
        }))

        await self._emit("speaking", text)
        interrupt_task = asyncio.create_task(self.interrupt.wait())
        try:
            while True:
                recv_task = asyncio.create_task(ws_cartesia.recv())
                done, _ = await asyncio.wait(
                    {recv_task, interrupt_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if interrupt_task in done:
                    recv_task.cancel()
                    try:
                        await recv_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    return False

                try:
                    msg = json.loads(recv_task.result())
                except Exception:
                    continue

                if msg.get("context_id") != ctx:
                    continue

                t = msg["type"]
                if t == "chunk":
                    audio = base64.b64decode(msg["data"])
                    await ws_browser.send_bytes(audio)
                elif t == "done":
                    return True
                elif t == "error":
                    print(f"[Cartesia error] {msg.get('message')}")
                    return True
        finally:
            interrupt_task.cancel()
            try:
                await interrupt_task
            except asyncio.CancelledError:
                pass
            self.tts_active = False
            # 300ms immunity: prevents Deepgram events already in-flight at sentence
            # end from firing a false barge-in into the next sentence's gap.
            self.tts_immune_until = asyncio.get_running_loop().time() + 0.3

    async def _stream_response(
        self, messages: list[dict], ws_cartesia, ws_browser: WebSocket,
        system: str | None = None,
    ) -> tuple[str, str]:
        """Stream LLM response, speak sentences via TTS as they arrive.

        Returns (generated, spoken):
          generated — full text if stream completed, "" if interrupted mid-stream.
          spoken    — text actually delivered to user's ears (may be partial on interrupt).
        """
        buf = ""
        generated = ""
        spoken = ""
        interrupted = False

        async with anthropic_client.messages.stream(
            model=HAIKU_MODEL,
            max_tokens=400,
            system=system if system is not None else self._build_system_prompt(),
            messages=messages,
        ) as stream:
            async for token in stream.text_stream:
                if self.interrupt.is_set():
                    interrupted = True
                    break
                print(token, end="", flush=True)
                buf += token
                generated += token
                sentences, buf = flush_sentences(buf)
                for s in sentences:
                    ok = await self._tts_speak(ws_cartesia, ws_browser, s)
                    if ok:
                        spoken += s + " "
                    else:
                        interrupted = True
                        break
                if interrupted:
                    break

        if not interrupted:
            remainder = buf.strip()
            if remainder and not remainder.startswith("[SEARCH:"):
                ok = await self._tts_speak(ws_cartesia, ws_browser, remainder)
                if ok:
                    spoken += remainder

        print()
        return ("" if interrupted else generated, spoken.strip())

    async def _respond(self, utterance: str, ws_cartesia, ws_browser: WebSocket) -> None:
        if self.pending_result:
            pr = self.pending_result
            self.pending_result = None
            delivery = f"I did get results for that. {pr['spoken']}"
            print(f"\n[MeTs] (pending) {delivery}")
            await self._tts_speak(ws_cartesia, ws_browser, delivery)
            self.history.append({
                "role": "assistant",
                "content": f"[Search for '{pr['query']}']: {pr['spoken']}\n\nSearch data: {pr['raw']}",
            })

        self.history.append({"role": "user", "content": utterance})
        print(f"\n[You]  {utterance}")
        print("[MeTs] ", end="", flush=True)

        self.interrupt.clear()
        self.is_responding = True
        self.tts_immune_until = asyncio.get_running_loop().time() + 1.0
        history_committed = False

        await self._emit("user", utterance)
        await self._emit("thinking")

        try:
            generated, spoken = await self._stream_response(
                self.history, ws_cartesia, ws_browser
            )
            interrupted = (generated == "")

            if generated:
                # Full stream completed — check for search token
                search_match = re.search(r'\[SEARCH:\s*(.+?)\]', generated)
                if search_match:
                    query = search_match.group(1).strip()
                    print(f"[Search] {query}")
                    await self._emit("searching", query)

                    bridge_ok = await self._tts_speak(
                        ws_cartesia, ws_browser, random.choice(SEARCH_BRIDGES)
                    )
                    if bridge_ok:
                        search_task = asyncio.create_task(brave_search(query))
                        try:
                            results = await asyncio.wait_for(
                                asyncio.shield(search_task), timeout=2.5
                            )
                        except asyncio.TimeoutError:
                            if not self.interrupt.is_set():
                                await self._tts_speak(
                                    ws_cartesia, ws_browser, "Still on it."
                                )
                            results = await search_task

                        print(f"[Search] {results[:120]}...")

                        if self.interrupt.is_set():
                            # Interrupted before response could start (during search wait).
                            # Queue pending — it delivers the context next turn.
                            await self._queue_pending_result(query, results)
                            interrupted = True
                        else:
                            search_system = (
                                self._build_system_prompt()
                                + f"\n\nSearch results for '{query}':\n{results}\n\n"
                                "Answer the user's question. Do not reference the search."
                            )
                            print("[MeTs] ", end="", flush=True)
                            await self._emit("thinking")
                            _, search_spoken = await self._stream_response(
                                self.history, ws_cartesia, ws_browser,
                                system=search_system,
                            )
                            interrupted = self.interrupt.is_set()

                            # Always commit: search data + what was spoken.
                            # Happens even when response was interrupted mid-TTS —
                            # search_spoken holds what the user actually heard.
                            self.history.append({
                                "role": "assistant",
                                "content": (
                                    f"[Search for '{query}': {results}]\n\n"
                                    + (search_spoken.strip() if search_spoken.strip() else "[interrupted before response]")
                                ),
                            })
                            history_committed = True
                else:
                    # Direct response — record what was spoken
                    if spoken:
                        self.history.append({"role": "assistant", "content": spoken})
                        history_committed = True
                        asyncio.create_task(self._extract_facts(utterance, spoken))
                        asyncio.create_task(self._compact_history())
            else:
                # Stream interrupted before completion — record what was spoken (if any)
                if spoken:
                    self.history.append({"role": "assistant", "content": spoken})
                    history_committed = True

        finally:
            self.is_responding = False
            await self._emit("listening")

        if not history_committed:
            if self.pending_result:
                # Pending result will deliver as assistant turn next call — keep user Q
                print("[MeTs] ← interrupted (pending queued)")
            elif self.history and self.history[-1]["role"] == "user":
                self.history.pop()
                print("[MeTs] ← interrupted (no context)")

    async def run(self, ws_browser: WebSocket) -> None:
        self.facts_store = {}  # No carryover — clean slate each session
        self.history     = []
        print("[Pipeline] Session started, clean context.")

        await self._emit("connecting")

        transcript_queue: asyncio.Queue[str] = asyncio.Queue()
        dg = AsyncDeepgramClient(api_key=DEEPGRAM_API_KEY)

        async with dg.listen.v2.connect(
            model="flux-general-en",
            encoding="linear16",
            sample_rate=MIC_RATE,
        ) as dg_socket:

            async def on_message(msg):
                if isinstance(msg, ListenV2TurnInfo):
                    msg_type   = "TurnInfo"
                    event      = msg.event
                    transcript = msg.transcript
                    conf       = msg.end_of_turn_confidence
                elif isinstance(msg, dict):
                    msg_type   = msg.get("type", "")
                    event      = msg.get("event", "")
                    transcript = msg.get("transcript", "")
                    conf       = msg.get("end_of_turn_confidence", 0)
                else:
                    return

                # Fix: ignore connection acks, keepalives, non-turn messages
                if msg_type != "TurnInfo":
                    return

                bar = "█" * int(conf * 20)
                print(f"[DG] {event:<18} eot={conf:.2f} {bar:<20} | {repr(transcript)}")

                loop = asyncio.get_running_loop()

                if event in ("EagerEndOfTurn", "EndOfTurn") and transcript.strip():
                    if self.is_responding and loop.time() > self.tts_immune_until:
                        # Transcript-confirmed barge-in: user said actual words.
                        # No wake word — any words qualify. Equivalent to OpenAI
                        # semantic VAD. Immunity window prevents sentence-gap false fires.
                        print(f"[DG] ← barge-in ({event})")
                        self.interrupt.set()
                        await self._emit("listening")
                    elif not self.is_responding:
                        while not transcript_queue.empty():
                            try:
                                transcript_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        print("[DG] → LLM")
                        await transcript_queue.put(transcript)

            async def on_dg_open(_):
                print("[Deepgram] Connected ✓")
                await self._emit("dg_ready")

            dg_socket.on(EventType.MESSAGE, on_message)
            dg_socket.on(EventType.OPEN,    on_dg_open)
            dg_socket.on(EventType.CLOSE,   lambda _: print("[Deepgram] Closed"))

            async with websockets.connect(
                CARTESIA_WS_URL,
                additional_headers={"X-API-Key": CARTESIA_API_KEY},
            ) as ws_cartesia:
                print("[Cartesia] Connected ✓")
                await self._emit("listening")

                asyncio.create_task(dg_socket.start_listening())

                async def receive_audio():
                    try:
                        while True:
                            data = await ws_browser.receive_bytes()
                            await dg_socket.send_media(data)
                    except Exception as e:
                        print(f"[Pipeline] mic feed stopped: {e}")

                asyncio.create_task(receive_audio())

                try:
                    while True:
                        utterance = await transcript_queue.get()
                        await self._respond(utterance, ws_cartesia, ws_browser)
                except Exception as e:
                    print(f"[Pipeline] session ended: {e}")
                finally:
                    save_history(self.history)
                    save_facts(self.facts_store)
                    try:
                        await dg_socket.send_close_stream()
                    except Exception:
                        pass
                    print("[MeTs] Session closed, history + facts saved.")
