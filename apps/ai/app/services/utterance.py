"""
One push-to-talk utterance, transcribed WHILE it is recorded (used by WS /voice and WS /voice/command).

    audio_start  → Utterance(stt, mime, hint, on_partial)   opens the provider stream (if stt.streams)
    binary frame → feed(frame)                              forwarded to the provider at once
                     … on_partial(STTUpdate)                partial transcripts, to show while the caller speaks
    audio_end    → await text()                             end of audio: only the last words are left to finalize

With a streaming STT (Soniox, Deepgram, mock) the transcript is ready a few hundred ms after the release, instead
of transcribing the whole recording then. Every frame is also kept: if the live stream breaks (network, provider
error, no final words in time), text() transcribes the whole recording the classic way, so the utterance is never
lost. cancel() (barge-in, client gone) closes the provider stream.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing

from app.clients import STTClient
from app.clients.base import STTUpdate

from .vocabulary import stt_hint

FINAL_TIMEOUT_S = 5.0
# Early start (mar. 17:30): Soniox's finalize took ~1.2 s after the release, while its provisional text was already the
# final one. If the live text has not changed for EARLY_SETTLE_S at the release, the turn starts on it; the final text
# keeps coming in the background and the voice session restarts the turn if it differs (never a write before that).
EARLY_SETTLE_S = 0.15  # mar. 19:30: 0.3 added ~0.15 s to every turn
EARLY_MAX_WAIT_S = 0.6  # after audio_end, how long to wait for the live stream's final words before the fallback


class Utterance:
    def __init__(self, stt: STTClient, mime: str, hint: str | None, on_partial: Callable[[STTUpdate], Awaitable[None]]):
        self.stt, self.mime, self.hint, self.on_partial = stt, mime, hint, on_partial
        self.frames: list[bytes] = []
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()  # frames for the live stream, None = end of audio
        # Diagnosis timestamps (time.perf_counter), read by the voice session for TurnTimings. No effect on behaviour.
        self.started_at = time.perf_counter()  # audio_start
        self.stream_ready_at: float | None = None  # the provider stream asked for its first frame (vocabulary + connect)
        self.ended_at: float | None = None  # audio_end: text() called
        self.backlog_frames: int | None = None  # frames still queued for the provider at audio_end
        self.finalize_sent_at: float | None = None  # all audio handed to the provider: it now sends its finalize
        self.final_at: float | None = None  # final transcript available
        self.fallback = False  # the live stream failed: the whole recording was re-transcribed
        self.live = asyncio.create_task(self._listen()) if stt.streams else None
        self.last_partial = ""  # the live text so far (final + provisional words)
        self.last_partial_at: float | None = None  # when it last changed

    def feed(self, frame: bytes) -> None:
        self.frames.append(frame)
        self.queue.put_nowait(frame)

    def _end_audio(self) -> None:
        if self.ended_at is None:
            self.ended_at = time.perf_counter()
            self.backlog_frames = self.queue.qsize()
            self.queue.put_nowait(None)

    async def early_text(self) -> tuple[str, bool]:
        """Call at audio_end: (text, early). early=True: the settled live text, before the provider's final words —
        then `final()` gives the definitive one. early=False: the final transcript itself."""
        self._end_audio()
        if not self.live:
            return await self.final(), False
        while time.perf_counter() - self.ended_at < EARLY_MAX_WAIT_S:
            if self.live.done():
                return await self.final(), False
            if self.last_partial and self.last_partial_at and time.perf_counter() - self.last_partial_at >= EARLY_SETTLE_S:
                return self.last_partial, True
            await asyncio.wait([self.live], timeout=0.03)
        return await self.final(), False

    async def text(self) -> str:
        """Call at audio_end: the final transcript."""
        self._end_audio()
        return await self.final()

    async def final(self) -> str:
        """The definitive transcript (live stream's final words, else the whole recording re-transcribed)."""
        self._end_audio()
        if self.live:
            try:
                text = await asyncio.wait_for(self.live, FINAL_TIMEOUT_S)  # on timeout the stream is cancelled
                self.final_at = time.perf_counter()
                return text
            except Exception as e:
                print(f"[ai] live STT failed ({type(e).__name__}: {e}): transcribing the whole recording", flush=True)
        self.fallback = bool(self.live)  # a non-streaming STT transcribing the recording is its normal path
        hint = await stt_hint(self.stt.name, self.hint)
        text = await self.stt.transcribe(b"".join(self.frames), self.mime, hint)
        self.final_at = time.perf_counter()
        return text

    def cancel(self) -> None:
        if not self.live:
            return
        if not self.live.done():
            self.live.cancel()
        elif not self.live.cancelled():
            self.live.exception()  # a stream that already failed: nobody will read it, that's fine

    async def _audio(self) -> AsyncIterator[bytes]:
        if self.stream_ready_at is None:
            self.stream_ready_at = time.perf_counter()  # the provider stream is open and asks for audio
        while (frame := await self.queue.get()) is not None:
            yield frame
        self.finalize_sent_at = time.perf_counter()  # end of audio reached the provider adapter: finalize goes now

    async def _listen(self) -> str:
        hint = await stt_hint(self.stt.name, self.hint)  # cached; frames wait in the queue meanwhile
        shown = None
        # aclosing: leaving early (final words, cancellation) closes the provider's socket right away
        async with aclosing(self.stt.transcribe_stream(self._audio(), self.mime, hint)) as updates:  # type: ignore[type-var]
            async for update in updates:
                if update.final:
                    return update.text
                if update.text != self.last_partial:
                    self.last_partial, self.last_partial_at = update.text, time.perf_counter()
                if update.text != shown:
                    shown = update.text
                    await self.on_partial(update)
        return shown or ""
