"""
Where do the speech-to-text milliseconds go? (latency diagnosis — run on a machine that reaches the providers)

    make stt-probe            (or: cd apps/ai && uv run python -m app.stt_probe)

1. The TTS of .env (ElevenLabs) says a typical order sentence once → an mp3 "caller".
2. That audio is streamed to the STT of .env (Soniox) at REAL-TIME pace, 100 ms per chunk, like the microphone, through
   the same adapter as a call (transcribe_stream), with three vocabularies: the full company list the agent sends
   today, its first 50 terms, and none.
3. For each run: stream ready (connection), first partial, end of audio → final transcript (the finalize, i.e. what
   the caller waits for after releasing Space), and the text heard.

Nothing is written anywhere; keys are read from .env and never printed. Costs a few cents of TTS + STT.
"""

import asyncio
import statistics
import time
from collections.abc import AsyncIterator

from app.clients import get_stt_client, get_tts_client
from app.config import settings
from app.services.vocabulary import company_terms

SENTENCE = "Bonjour, c'est Jean-Marc du Panier Savoyard du Grand-Bornand. Mets-moi douze reblochons fermiers et trois kilos de diots pour samedi."  # noqa: E501
CHUNK_S = 0.1  # MediaRecorder sends a chunk every 100 ms
MP3_BYTES_PER_S = 16_000  # ElevenLabs mp3_44100_128 = 128 kbit/s
RUNS = 3


async def paced(audio: bytes, marks: dict) -> AsyncIterator[bytes]:
    """The recording, one 100 ms chunk at a time, in real time (the caller speaks); marks the end of speech."""
    step = int(MP3_BYTES_PER_S * CHUNK_S)
    marks["ready"] = time.perf_counter()
    for i in range(0, len(audio), step):
        yield audio[i : i + step]
        await asyncio.sleep(CHUNK_S)
    marks["end"] = time.perf_counter()


async def one_run(stt, audio: bytes, hint: str | None) -> dict:
    marks: dict = {"start": time.perf_counter()}
    text = ""
    async for update in stt.transcribe_stream(paced(audio, marks), "audio/mpeg", hint):
        marks.setdefault("first_partial", time.perf_counter())
        text = update.text
        if update.final:
            marks["final"] = time.perf_counter()
            break
    ms = lambda a, b: int((marks[b] - marks[a]) * 1000) if a in marks and b in marks else None  # noqa: E731
    return {"connect": ms("start", "ready"), "first_partial": ms("ready", "first_partial"), "finalize": ms("end", "final"), "text": text}


async def main() -> None:
    stt, tts = get_stt_client(), get_tts_client()
    if stt.name == "mock" or tts.name == "mock" or not stt.streams:
        print(f"Needs a real streaming STT and a real TTS in .env (now: STT={stt.name}, TTS={tts.name}). See make doctor.")
        return
    print(f"STT {stt.name} (model {getattr(stt, 'model', '?')}), TTS {tts.name}. Generating the caller's sentence…")
    try:
        result = await tts.synthesize(SENTENCE, settings.tts.voice or None)
        audio = b"".join([c async for c in result.chunks])
    except Exception as e:
        print(f"  TTS {tts.name} unreachable ({type(e).__name__}: {str(e)[:160]}). Run it where the providers are reachable.")
        return
    print(f"  {len(audio)} bytes ≈ {len(audio) / MP3_BYTES_PER_S:.1f} s of speech, streamed in real time\n")

    terms = await company_terms()
    if not terms:
        print("  (ERP not reachable: no company vocabulary; start the services to test it)\n")
    variants = [("full vocabulary", terms), ("first 50 terms", terms[:50]), ("no vocabulary", [])]
    print(f"{'vocabulary':18} {'terms':>5} {'chars':>6} | {'connect':>8} {'1st partial':>11} {'END→FINAL':>10} | text")
    summary = []
    for label, t in variants:
        hint = ", ".join(t) or None
        finals = []
        for _ in range(RUNS):
            try:
                r = await one_run(stt, audio, hint)
            except Exception as e:  # report the provider error and keep probing the other variants
                print(f"{label:18} {len(t):5} {len(hint or ''):6} | ERROR {type(e).__name__}: {str(e)[:120]}")
                continue
            finals.append(r["finalize"])
            print(f"{label:18} {len(t):5} {len(hint or ''):6} | {r['connect']!s:>6} ms {r['first_partial']!s:>8} ms {r['finalize']!s:>7} ms | {r['text'][:70]}")
        if finals := [f for f in finals if f is not None]:
            summary.append((label, statistics.median(finals)))
    print("\nEND→FINAL = what the caller waits for after the end of speech (finalize), median per vocabulary:")
    for label, m in summary:
        print(f"  {label:18} {m:6.0f} ms")
    print("\nCompare with the Voix page (STT line under each turn): if the page shows much more than END→FINAL here, the")
    print("delay is on the browser / upload side (mic tail, frames queued, stream opened late), not Soniox's finalize.")


if __name__ == "__main__":
    asyncio.run(main())
