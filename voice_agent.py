#!/usr/bin/env python3
"""
MeTs Voice Agent
Mic → Deepgram Flux (STT) → Claude Haiku 4.5 (LLM) → Cartesia Sonic (TTS) → Speaker

Memory layers:
  - Rolling summary: compacts old turns into a summary block when history grows long.
    Keeps last KEEP_RECENT_TURNS verbatim. Runs as a background task after each turn.
  - Fact extraction: pulls persistent facts (preferences, location, style) from each exchange
    and merges them into ~/.mets_facts.json. Injected into the system prompt every turn.
    Also runs in the background — zero latency impact.

Interruption-aware: StartOfTurn/TurnResumed cancels in-flight LLM + TTS instantly.
"""

import argparse
import asyncio
import base64
import json
import os
import re
import struct
import sys
import threading
from pathlib import Path

import httpx
import pyaudio
import websockets
from anthropic import AsyncAnthropic
from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.listen.v2.types import ListenV2TurnInfo
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

# ── Config ─────────────────────────────────────────────────────────────────────

DEEPGRAM_API_KEY  = os.environ["DEEPGRAM_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CARTESIA_API_KEY  = os.environ["CARTESIA_API_KEY"]
BRAVE_API_KEY     = os.environ.get("BRAVE_API_KEY", "")

MIC_RATE  = 16000
MIC_CHUNK = 4000
TTS_RATE  = 22050

HAIKU_MODEL    = "claude-haiku-4-5"
CARTESIA_VOICE = "f4a3a8e4-694c-4c45-9ca0-27caf97901b5"  # Gavin - Friendly Vibe
CARTESIA_MODEL = "sonic-3.5"
CARTESIA_WS_URL = "wss://api.cartesia.ai/tts/websocket?cartesia_version=2026-03-01"

# Memory
HISTORY_FILE        = Path.home() / ".mets_history.json"
FACTS_FILE          = Path.home() / ".mets_facts.json"
COMPACTION_THRESHOLD = 10   # turns (20 messages) before compaction triggers
KEEP_RECENT_TURNS   = 6    # turns to keep verbatim after compaction
MAX_FACTS           = 30   # cap on stored fact entries

SYSTEM_BASE = (
    "You are MeTs, a concise voice AI assistant built on a Raspberry Pi. "
    "Respond in 1–3 short sentences. "
    "Plain spoken English only — no markdown, bullet points, or lists. "
    "If the user asks about something that requires up-to-date information NOT already "
    "visible in the conversation (news, live weather, current prices, recent events), "
    "output exactly [SEARCH: your search query] with no other text. "
    "If the answer can be derived from information already in the conversation — including "
    "unit conversions, calculations, or follow-up questions — answer directly without searching."
)

# ── State ──────────────────────────────────────────────────────────────────────

history:        list[dict]      = []
facts_store:    dict            = {}
pending_result: dict | None     = None   # search completed but interrupted before speaking
is_responding                   = False
interrupt                       = asyncio.Event()

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


def save_history() -> None:
    try:
        HISTORY_FILE.write_text(json.dumps(history[-(KEEP_RECENT_TURNS * 2):]))
    except Exception:
        pass


def load_facts() -> dict:
    try:
        return json.loads(FACTS_FILE.read_text())
    except Exception:
        return {}


def save_facts() -> None:
    try:
        FACTS_FILE.write_text(json.dumps(facts_store, indent=2))
    except Exception:
        pass


def build_system_prompt() -> str:
    if not facts_store:
        return SYSTEM_BASE
    lines = "\n".join(f"- {k}: {v}" for k, v in list(facts_store.items())[:MAX_FACTS])
    return SYSTEM_BASE + f"\n\nPersistent context about this user:\n{lines}"


# ── Background memory tasks ────────────────────────────────────────────────────

async def extract_facts(utterance: str, response: str) -> None:
    """
    Single Haiku call: reads current fact store, extracts any new persistent facts
    from the exchange, merges, writes back. Runs in background — no latency impact.
    """
    global facts_store
    try:
        result = await anthropic_client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    "You maintain a persistent memory store for a personal voice AI assistant.\n\n"
                    f"Current memory: {json.dumps(facts_store)}\n\n"
                    f"New exchange:\nUser: {utterance}\nAssistant: {response}\n\n"
                    "Extract any facts that will remain true in future conversations: "
                    "preferences, location, name, communication style, recurring topics, "
                    "standing decisions. Skip one-off details. "
                    "Update conflicting entries with the newer value. "
                    f"Keep total under {MAX_FACTS} entries. "
                    "Return only the updated JSON object, or the unchanged object if nothing new."
                ),
            }],
        )
        updated = json.loads(result.content[0].text)
        if updated != facts_store:
            facts_store = updated
            save_facts()
            print(f"[Memory] Facts updated → {len(facts_store)} entries")
    except Exception as e:
        print(f"[Memory] Fact extraction failed: {e}", file=sys.stderr)


async def compact_history() -> None:
    """
    When history exceeds COMPACTION_THRESHOLD turns, compress the older portion
    into a summary block and replace it. Keeps KEEP_RECENT_TURNS verbatim.
    Runs in background.
    """
    global history
    if len(history) // 2 <= COMPACTION_THRESHOLD:
        return

    keep  = KEEP_RECENT_TURNS * 2
    old   = history[:-keep]
    recent = history[-keep:]

    text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'MeTs'}: {m['content'][:300]}"
        for m in old
    )
    try:
        result = await anthropic_client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=250,
            messages=[{
                "role": "user",
                "content": (
                    "Summarise this conversation segment in 4–6 sentences. "
                    "Preserve specific facts, numbers, decisions, and user preferences. "
                    "Be concrete — avoid vague summaries.\n\n" + text
                ),
            }],
        )
        summary = result.content[0].text.strip()
        history = [
            {"role": "user",      "content": f"[Earlier conversation: {summary}]"},
            {"role": "assistant", "content": "Understood, I have that context."},
        ] + recent
        print(f"[Memory] Compacted {len(old)} messages → summary block. "
              f"History now {len(history)} messages.")
    except Exception as e:
        print(f"[Memory] Compaction failed: {e}", file=sys.stderr)


# ── Sentence chunker ───────────────────────────────────────────────────────────

def flush_sentences(buf: str) -> tuple[list[str], str]:
    parts = re.split(r"(?<=[.!?])\s+", buf)
    if len(parts) == 1:
        if re.search(r"[.!?]\s*$", buf):
            return [buf.strip()], ""
        return [], buf
    return [p for p in parts[:-1] if p.strip()], parts[-1]


# ── TTS ────────────────────────────────────────────────────────────────────────

async def tts_speak(ws, text: str, spk, loop) -> bool:
    """Stream one sentence from Cartesia. Returns False if interrupted."""
    text = text.strip()
    if not text:
        return True

    ctx = f"mets-{loop.time():.3f}".replace(".", "-")
    await ws.send(json.dumps({
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

    interrupt_task = asyncio.create_task(interrupt.wait())
    try:
        while True:
            recv_task = asyncio.create_task(ws.recv())
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
                await loop.run_in_executor(None, spk.write, audio)
            elif t == "done":
                return True
            elif t == "error":
                print(f"[Cartesia error] {msg.get('message')}", file=sys.stderr)
                return True
    finally:
        interrupt_task.cancel()
        try:
            await interrupt_task
        except asyncio.CancelledError:
            pass


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


# ── Stubborn pending delivery ──────────────────────────────────────────────────

async def _queue_pending_result(query: str, raw_results: str) -> None:
    """
    Search completed but user interrupted before results were spoken.
    Generate a 1-sentence spoken summary and hold it for delivery on the next turn.
    Awaited directly (not background) — we're already in the interrupted path,
    not blocking anything the user is waiting on.
    """
    global pending_result
    try:
        r = await anthropic_client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=80,
            messages=[{"role": "user", "content":
                f"In one short spoken sentence (no markdown, no lists), summarise "
                f"the search result for '{query}':\n{raw_results[:600]}"}],
        )
        spoken = r.content[0].text.strip()
    except Exception:
        spoken = f"I did find results for {query} but couldn't summarise them."
    pending_result = {"query": query, "spoken": spoken, "raw": raw_results}
    print(f"[Search] Queued pending result for '{query}'")


# ── LLM streaming ──────────────────────────────────────────────────────────────

async def stream_response(messages: list[dict], ws_cartesia, spk, loop) -> str:
    """Stream an LLM response, speak it sentence by sentence. Returns '' if interrupted."""
    buf           = ""
    full_response = ""
    interrupted   = False

    async with anthropic_client.messages.stream(
        model=HAIKU_MODEL,
        max_tokens=400,
        system=build_system_prompt(),
        messages=messages,
    ) as stream:
        async for token in stream.text_stream:
            if interrupt.is_set():
                interrupted = True
                break
            print(token, end="", flush=True)
            buf           += token
            full_response += token
            sentences, buf = flush_sentences(buf)
            for s in sentences:
                if not await tts_speak(ws_cartesia, s, spk, loop):
                    interrupted = True
                    break
            if interrupted:
                break

    if not interrupted:
        remainder = buf.strip()
        if remainder:
            await tts_speak(ws_cartesia, remainder, spk, loop)

    print()
    return "" if interrupted else full_response


# ── Main response pipeline ─────────────────────────────────────────────────────

async def respond(utterance: str, ws_cartesia, spk, loop) -> None:
    global history, is_responding, pending_result

    # ── Stubborn delivery: if a previous search finished while the user was
    # interrupting, surface it now before handling the new utterance.
    # One attempt only — if interrupted again here, drop it silently.
    if pending_result:
        pr = pending_result
        pending_result = None
        delivery = f"Quick note — I did finish that search. {pr['spoken']}"
        print(f"\n[MeTs] (pending) {delivery}")
        await tts_speak(ws_cartesia, delivery, spk, loop)
        # Fill the history gap so roles stay alternating
        history.append({
            "role": "assistant",
            "content": f"[Delivered pending result for '{pr['query']}']: {pr['spoken']}\n[Raw: {pr['raw']}]",
        })

    history.append({"role": "user", "content": utterance})
    print(f"\n[You]  {utterance}")
    print("[MeTs] ", end="", flush=True)

    interrupt.clear()
    is_responding = True
    full_response = ""
    interrupted   = False

    try:
        full_response = await stream_response(history, ws_cartesia, spk, loop)
        interrupted   = (full_response == "")

        if not interrupted:
            search_match = re.search(r'\[SEARCH:\s*(.+?)\]', full_response)
            if search_match:
                query = search_match.group(1).strip()
                print(f"[Search] {query}")
                full_response = ""

                # Guard 1: if user barges in during the bridge phrase, abort entirely.
                bridge_ok = await tts_speak(ws_cartesia, "On it, looking that up.", spk, loop)
                if not bridge_ok:
                    # Never searched — clean up the user message and bail.
                    if history and history[-1]["role"] == "user":
                        history.pop()
                    interrupted = True
                else:
                    results = await brave_search(query)
                    print(f"[Search] {results[:120]}...")

                    # Guard 2: user interrupted while search was in flight.
                    # Results are in hand — queue for stubborn delivery next turn.
                    if interrupt.is_set():
                        await _queue_pending_result(query, results)
                        # Don't pop the user message — pending delivery will serve as reply.
                        interrupted = True
                    else:
                        search_messages = history + [{
                            "role": "user",
                            "content": (
                                f"Web search results for '{query}':\n{results}\n\n"
                                "Give the user a spoken answer based on these results."
                            ),
                        }]
                        print("[MeTs] ", end="", flush=True)
                        full_response = await stream_response(search_messages, ws_cartesia, spk, loop)
                        interrupted   = (full_response == "")

                        if full_response.strip():
                            history.append({
                                "role": "assistant",
                                "content": f"[Search data for '{query}': {results}]\n\n{full_response}",
                            })
                            full_response = ""

    finally:
        is_responding = False

    if full_response.strip():
        history.append({"role": "assistant", "content": full_response})
        asyncio.create_task(extract_facts(utterance, full_response))
        asyncio.create_task(compact_history())
    elif interrupted:
        if history and history[-1]["role"] == "user":
            history.pop()
        print("[MeTs] ← interrupted")


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    global history, facts_store

    parser = argparse.ArgumentParser(description="MeTs Voice Agent")
    parser.add_argument(
        "-N", "--new",
        action="store_true",
        help="Start a fresh session — ignore saved history and facts",
    )
    args = parser.parse_args()

    if args.new:
        history     = []
        facts_store = {}
        print("[Memory] Fresh session — history and facts cleared.")
    else:
        facts_store = load_facts()
        history     = load_history()
        if facts_store:
            print(f"[Memory] {len(facts_store)} persistent facts loaded.")

    loop = asyncio.get_running_loop()

    print("[MeTs] Initialising audio...")
    pa = pyaudio.PyAudio()

    print("[Audio] Input devices:")
    default_idx = pa.get_default_input_device_info()["index"]
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["maxInputChannels"] > 0:
            marker = " ← default" if i == default_idx else ""
            print(f"  [{i}] {d['name']}{marker}")

    macbook_mic = next(
        pa.get_device_info_by_index(i)
        for i in range(pa.get_device_count())
        if "MacBook Pro Microphone" in pa.get_device_info_by_index(i)["name"]
        and pa.get_device_info_by_index(i)["maxInputChannels"] > 0
    )
    default_out = pa.get_default_output_device_info()
    print(f"[Audio] Input:  [{int(macbook_mic['index'])}] {macbook_mic['name']}")
    print(f"[Audio] Output: [{int(default_out['index'])}] {default_out['name']}")

    mic = pa.open(
        format=pyaudio.paInt16, channels=1, rate=MIC_RATE,
        input=True, input_device_index=int(macbook_mic["index"]),
        frames_per_buffer=MIC_CHUNK,
    )
    spk = pa.open(
        format=pyaudio.paInt16, channels=1, rate=TTS_RATE,
        output=True,
    )

    transcript_queue: asyncio.Queue[str] = asyncio.Queue()

    print("[MeTs] Connecting to Deepgram...")
    dg = AsyncDeepgramClient(api_key=DEEPGRAM_API_KEY)

    async with dg.listen.v2.connect(
        model="flux-general-en",
        encoding="linear16",
        sample_rate=MIC_RATE,
    ) as dg_socket:

        async def on_open(data):
            print("[Deepgram] Connected ✓")

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

            if msg_type != "TurnInfo":
                return

            bar = "█" * int(conf * 20)
            print(f"[DG] {event:<18} eot={conf:.2f} {bar:<20} | {repr(transcript)}")

            if event in ("StartOfTurn", "TurnResumed") and is_responding:
                print("[DG] ← barge-in")
                interrupt.set()
            elif event in ("EagerEndOfTurn", "EndOfTurn") and transcript.strip():
                while not transcript_queue.empty():
                    try:
                        transcript_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                print("[DG] → LLM")
                await transcript_queue.put(transcript)

        async def on_error(err):
            print(f"[DG] ERROR: {err}", file=sys.stderr)

        async def on_close(_):
            print("[DG] Connection closed")

        dg_socket.on(EventType.OPEN,    on_open)
        dg_socket.on(EventType.MESSAGE, on_message)
        dg_socket.on(EventType.ERROR,   on_error)
        dg_socket.on(EventType.CLOSE,   on_close)

        print("[MeTs] Connecting to Cartesia...")
        async with websockets.connect(
            CARTESIA_WS_URL,
            additional_headers={"X-API-Key": CARTESIA_API_KEY},
        ) as ws_cartesia:
            print("[MeTs] Cartesia connected ✓")

            # Spoken orientation so the user knows the session state
            if args.new:
                await tts_speak(ws_cartesia, "Starting fresh.", spk, loop)
            elif history:
                await tts_speak(ws_cartesia, "Picking up from our last session.", spk, loop)

            print("[MeTs] Ready — speak now. (Ctrl+C to quit)\n")

            def rms(data: bytes) -> int:
                n = len(data) // 2
                if n == 0:
                    return 0
                shorts = struct.unpack(f"<{n}h", data)
                return int((sum(s * s for s in shorts) / n) ** 0.5)

            def mic_reader():
                frames = 0
                while True:
                    try:
                        data = mic.read(MIC_CHUNK, exception_on_overflow=False)
                        asyncio.run_coroutine_threadsafe(dg_socket.send_media(data), loop)
                        frames += 1
                        if frames % 12 == 0:
                            level = rms(data)
                            bar   = "█" * min(20, level // 100)
                            print(f"[Mic] level={level:5d}  {bar}")
                    except OSError as e:
                        print(f"[Mic] ERROR: {e}", file=sys.stderr)
                        break

            threading.Thread(target=mic_reader, daemon=True).start()

            async def listen_task():
                try:
                    await dg_socket.start_listening()
                except Exception as e:
                    print(f"[DG] start_listening crashed: {e}", file=sys.stderr)

            asyncio.create_task(listen_task())

            try:
                while True:
                    utterance = await transcript_queue.get()
                    await respond(utterance, ws_cartesia, spk, loop)
            except KeyboardInterrupt:
                pass
            finally:
                save_history()
                save_facts()
                await dg_socket.send_close_stream()
                mic.close()
                spk.close()
                pa.terminate()
                print("\n[MeTs] Stopped.")


if __name__ == "__main__":
    asyncio.run(main())
