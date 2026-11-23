"""Speech-to-text adapters. Owned by Pod A.

STT_PROVIDER = mock | openai | deepgram   (set in .env)
All adapters return (text, confidence, words, latency_ms).
The openai/deepgram adapters are written against their public REST APIs but were NOT
exercised offline: first Pod A task after 19:30 = run `make stt-smoke` with a real key.
Catalog vocabulary is passed as a bias prompt / keyterms — the single biggest accuracy
lever for product names ("lieu jaune", "faux-filet", "batavia").
"""
from __future__ import annotations

import os
import random
import re
import time
from functools import lru_cache

import httpx

from shared_contracts.schemas import WordTiming

PROVIDER = os.getenv("STT_PROVIDER", "mock")


@lru_cache
def catalog_vocab(limit: int = 80) -> list[str]:
    from pod_b_agent.catalog import load_catalog  # read-only use of Pod B's loader
    words: list[str] = []
    for p in load_catalog().products:
        words += [p.label, *p.aliases]
    return list(dict.fromkeys(words))[:limit]


async def transcribe_bytes(audio: bytes, mime: str = "audio/webm") -> tuple[str, float, list[WordTiming], int]:
    t0 = time.perf_counter()
    if PROVIDER == "openai":
        text, conf, words = await _openai(audio, mime)
    elif PROVIDER == "deepgram":
        text, conf, words = await _deepgram(audio, mime)
    else:
        raise RuntimeError("STT_PROVIDER=mock cannot transcribe audio; use /api/voice/simulate or set a provider")
    return text, conf, words, int((time.perf_counter() - t0) * 1000)


async def _openai(audio: bytes, mime: str) -> tuple[str, float, list[WordTiming]]:
    model = os.getenv("OPENAI_STT_MODEL", "gpt-4o-transcribe")
    prompt = "Commande téléphonique d'un restaurant à un grossiste alimentaire. Produits : " + ", ".join(catalog_vocab())
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            data={"model": model, "language": "fr", "prompt": prompt},
            files={"file": ("audio" + _ext(mime), audio, mime)},
        )
        r.raise_for_status()
        return r.json()["text"], 0.9, []


async def _deepgram(audio: bytes, mime: str) -> tuple[str, float, list[WordTiming]]:
    model = os.getenv("DEEPGRAM_MODEL", "nova-3")
    params: list[tuple[str, str]] = [("model", model), ("language", "fr"), ("smart_format", "true"),
                                     ("numerals", "true")]
    params += [("keyterm", v) for v in catalog_vocab(40)]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.deepgram.com/v1/listen", params=params, content=audio,
                         headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}", "Content-Type": mime})
        r.raise_for_status()
        alt = r.json()["results"]["channels"][0]["alternatives"][0]
        words = [WordTiming(w=w["word"], start_ms=int(w["start"] * 1000), end_ms=int(w["end"] * 1000),
                            conf=w.get("confidence", 0.9)) for w in alt.get("words", [])]
        return alt["transcript"], float(alt.get("confidence", 0.9)), words


def _ext(mime: str) -> str:
    return {"audio/webm": ".webm", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg", "audio/mp4": ".m4a"}.get(mime.split(";")[0], ".webm")


# ───────── test helper: simulate ASR errors on clean text ─────────
ASR_CONFUSIONS = [
    (r"\bbar\b", "barre"), (r"\bfaux-filet\b", "faut filet"), (r"\blieu jaune\b", "lieux jaunes"),
    (r"\bdorade\b", "daurade"), (r"\bsept\b", "cèpes"), (r"\bcent\b", "sans"), (r"\bvingt\b", "vin"),
    (r"\bpoireaux\b", "poids rots"), (r"\bmozzarella\b", "mozza"), (r"\bbatavia\b", "bata via"),
]


def add_asr_noise(text: str, p: float = 0.5, seed: int | None = None) -> str:
    rng = random.Random(seed)
    for pat, rep in ASR_CONFUSIONS:
        if rng.random() < p:
            text = re.sub(pat, rep, text, flags=re.I)
    return text
