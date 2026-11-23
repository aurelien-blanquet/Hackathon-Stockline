"""FastAPI wiring. Owned by the Architect — pods add routes in their own router.py only.

Run:  uvicorn app.main:app --reload --port 8000   (or `make run`)
UI:   http://localhost:8000/
"""
from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.bus import bus  # noqa: E402
from pod_a_voice.router import router as voice_router  # noqa: E402
from pod_b_agent.router import handle_transcript, router as agent_router  # noqa: E402
from shared_contracts.schemas import CONTRACT_VERSION  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(title="Stockline Voice Agent", version=CONTRACT_VERSION)
app.include_router(voice_router)
app.include_router(agent_router)
bus.subscribe("transcript", handle_transcript)

app.mount("/static", StaticFiles(directory=ROOT / "pod_c_ui" / "static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "pod_c_ui" / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    import os
    return {"ok": True, "contract": CONTRACT_VERSION, "extractor": os.getenv("EXTRACTOR", "rules"),
            "stt": os.getenv("STT_PROVIDER", "mock")}


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    bus.add_socket(websocket)
    try:
        while True:
            await websocket.receive_text()   # keepalive; UI sends nothing meaningful
    except WebSocketDisconnect:
        bus.remove_socket(websocket)
