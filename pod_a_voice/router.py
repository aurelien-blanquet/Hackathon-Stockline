"""Pod A HTTP surface: /api/voice/*. Owned by Pod A.

- POST /api/voice/simulate : text -> streamed TranscriptEvents (partials + finals) — demo & tests
- POST /api/voice/upload   : audio file (browser mic / .wav) -> STT -> final TranscriptEvent
- GET  /api/voice/cases    : synthetic cases for the demo dropdown
Telephony (Twilio/Vapi/LiveKit media streams) plugs in here later and publishes the same events.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.bus import bus
from shared_contracts.schemas import AudioMeta, TranscriptEvent

from .stt import PROVIDER, transcribe_bytes

router = APIRouter(prefix="/api/voice", tags=["pod_a_voice"])
ROOT = Path(__file__).resolve().parents[1]
_seq: dict[str, int] = {}


def _next(call_id: str) -> int:
    _seq[call_id] = _seq.get(call_id, -1) + 1
    return _seq[call_id]


class SimulateRequest(BaseModel):
    text: str
    customer_id: Optional[str] = None
    caller_number: Optional[str] = None
    call_id: Optional[str] = None
    words_per_chunk: int = 4
    chunk_delay_ms: int = 220
    confidence: float = 0.92


async def _stream(req: SimulateRequest, call_id: str) -> None:
    # one "final" per sentence, partials every few words — mimics streaming ASR
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", req.text) if s.strip()]
    for sent in sentences:
        words = sent.split()
        for i in range(req.words_per_chunk, len(words), req.words_per_chunk):
            await bus.publish("transcript", TranscriptEvent(
                call_id=call_id, seq=_next(call_id), text=" ".join(words[:i]), is_final=False,
                confidence=req.confidence, customer_id=req.customer_id, caller_number=req.caller_number))
            await asyncio.sleep(req.chunk_delay_ms / 1000)
        await bus.publish("transcript", TranscriptEvent(
            call_id=call_id, seq=_next(call_id), text=sent, is_final=True, confidence=req.confidence,
            customer_id=req.customer_id, caller_number=req.caller_number,
            audio=AudioMeta(source="mock", provider="mock", stt_latency_ms=180)))
        await asyncio.sleep(req.chunk_delay_ms / 1000)


@router.post("/simulate")
async def simulate(req: SimulateRequest) -> dict:
    call_id = req.call_id or f"sim-{uuid.uuid4().hex[:6]}"
    asyncio.create_task(_stream(req, call_id))
    return {"call_id": call_id}


@router.post("/upload")
async def upload(file: UploadFile = File(...), customer_id: Optional[str] = Form(None),
                 call_id: Optional[str] = Form(None)) -> dict:
    call_id = call_id or f"mic-{uuid.uuid4().hex[:6]}"
    audio = await file.read()
    try:
        text, conf, words, ms = await transcribe_bytes(audio, file.content_type or "audio/webm")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"STT failed ({PROVIDER}): {e}")
    ev = TranscriptEvent(call_id=call_id, seq=_next(call_id), text=text, confidence=conf, words=words,
                         customer_id=customer_id,
                         audio=AudioMeta(source="mic", provider=PROVIDER, stt_latency_ms=ms))
    await bus.publish("transcript", ev)
    return {"call_id": call_id, "text": text, "stt_ms": ms}


@router.get("/cases")
def cases() -> list[dict]:
    return [json.loads(l) for f in sorted((ROOT / "tests" / "synthetic").glob("*.jsonl"))
            for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
