"""
MeTs FastAPI server.

Routes:
  GET  /          → static/index.html (browser UI + dashboard)
  WS   /audio     → voice pipeline (PCM16 in, PCM16 out)
  WS   /events    → state stream for dashboard (JSON)
"""

import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from pipeline import VoicePipeline

app = FastAPI()


class EventBus:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def publish(self, event: dict) -> None:
        for q in list(self._queues):
            await q.put(event)


event_bus = EventBus()


@app.websocket("/audio")
async def audio_ws(websocket: WebSocket):
    await websocket.accept()
    print("[Server] Browser connected /audio")
    pipeline = VoicePipeline(event_bus=event_bus)
    try:
        await pipeline.run(websocket)
    except WebSocketDisconnect:
        print("[Server] Browser disconnected /audio")
    except Exception as e:
        print(f"[Server] /audio error: {e}")


@app.websocket("/events")
async def events_ws(websocket: WebSocket):
    await websocket.accept()
    q = event_bus.subscribe()
    try:
        while True:
            event = await q.get()
            await websocket.send_json(event)
    except (WebSocketDisconnect, Exception):
        event_bus.unsubscribe(q)


app.mount("/", StaticFiles(directory="static", html=True), name="static")
