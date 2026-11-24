"""
WS /voice — push-to-talk voice sessions (messages: app/schemas/voice.py).

One turn:
    audio_start … binary frames … audio_end   (or a typed `text` message)
      → STT, live: each frame goes to the provider as it arrives (services/utterance.py);
        "transcript" final:false while the caller speaks, then "transcript" final:true soon after audio_end
      → agent (voice mode) streaming "agent_text" / "agent_tool"
      → each finished sentence goes to TTS right away (sentence by sentence = first audio sooner)
      → "agent_audio_start" {mime}, binary audio chunks…, "agent_audio_end"   (one audio segment per turn)
      → "agent_done" {text, timings}

Barge-in: a new audio_start / text while the agent is still busy cancels the running turn (asyncio
cancellation); what was heard stays in the history, and of the agent's reply only what was actually voiced.

Team additions (GUIDE-VOIX 4.7, 4.8, 4.9, 5.2, 5.3):
  - filler: on the first tool call of a turn, if the agent has said nothing yet, a short pre-synthesised phrase
    (« Je regarde. ») plays at once (no TTS call: the audio was rendered when the connection opened);
  - warm-up: those renders also open the TTS connection before the caller first speaks;
  - spoken French: every sentence goes through speak_fr.to_speech() before TTS (prices, units, dates, ids,
    markdown), so the voice never says « dix-huit point cinq zéro euro slash kg »;
  - earlier first sound: the very first chunk of a reply may be cut at a comma once it is long enough;
  - honest history on barge-in: the model only remembers the sentences whose audio actually started.
"""

import asyncio
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import aclosing, suppress
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from app.agent import run_agent, sanitize_history
from app.agent.loop import ms_since
from app.agent.prompts import get_meta
from app.agent.speak_fr import to_speech
from app.clients import STTUpdate, TTSClient, get_llm_client, get_stt_client, get_tts_client
from app.clients.http import http_client
from app.config import settings
from app.schemas import (
    AgentAudioEndMessage,
    AgentAudioStartMessage,
    AgentDoneMessage,
    AgentTextMessage,
    AgentToolMessage,
    AudioEndMessage,
    AudioStartMessage,
    ChatMessage,
    ErrorEvent,
    ReadyMessage,
    ResetMessage,
    StartMessage,
    TextEvent,
    TextMessage,
    ToolCallEvent,
    ToolResultEvent,
    TranscriptMessage,
    TurnTimings,
    VoiceClientMessage,
    VoiceErrorMessage,
)
from app.schemas.base import WireModel
from app.tools import all_tools

from .utterance import Utterance
from .vocabulary import stt_hint

client_message = TypeAdapter(VoiceClientMessage)


@dataclass
class Conversation:
    id: str
    actor_name: str | None = None
    history: list[ChatMessage] = field(default_factory=list)
    fillers_used: int = 0  # rotates the filler phrases so the caller does not hear the same one every turn


# Said while the first tool runs, when the agent has said nothing yet. Short, varied, no promise about the result.
FILLERS = ["Je regarde.", "Un instant, je vérifie.", "Je regarde ça.", "Deux secondes.", "Je vérifie tout de suite."]

# First sound within a deadline (presentation: « le temps avant le premier mot »). If nothing has been said
# ACK_AFTER_S after the transcript is ready, a pre-rendered short acknowledgement plays, like a person on the phone,
# while the model and the tools work. At most ONE filler per turn: this one, or « Je regarde. » on the first tool call,
# whichever comes first. Counted as first sound in the timings: say so in DECISIONS.md.
ACK_AFTER_S = 0.35
ACKS = ["D'accord.", "Oui.", "Très bien."]
FIRST_ACK = "Oui, un instant."  # first turn of a call: the caller usually just said who they are

# Said when the STT returned nothing usable (noise, a mumble, Space released too early).
REPROMPTS = ["Pardon, je n'ai pas bien entendu, vous pouvez répéter ?", "Désolé, ça a coupé. Vous pouvez répéter ?"]

# (tts name, voice, text) → (mime, audio bytes): rendered once per process, at the first connection.
_filler_audio: dict[tuple[str, str | None, str], tuple[str, bytes]] = {}


async def warm_llm() -> None:
    """Open the TLS connection to the LLM provider before the first turn (kept alive in the shared pool,
    clients/http.py): the first model call then skips the handshake. No tokens spent. Never raises."""
    llm = get_llm_client()
    base = getattr(llm, "base_url", None)
    if not base or llm.provider == "mock":
        return
    with suppress(Exception):
        await http_client().get(base, timeout=5)


async def prerender_fillers(tts: TTSClient) -> None:
    """Synthesise the fillers in the background. Doubles as the TTS warm-up (GUIDE-VOIX 4.9: first TTS call ≈ 1.9 s
    cold, then 170–370 ms). Never raises: without a render, the filler is synthesised on the fly."""
    voice = settings.tts.voice or None
    for text in [FIRST_ACK, *ACKS, *FILLERS]:
        key = (tts.name, voice, text)
        if key in _filler_audio:
            continue
        try:
            result = await tts.synthesize(text, voice)
            async with aclosing(result.chunks) as chunks:  # type: ignore[type-var]
                audio = b"".join([chunk async for chunk in chunks])
            if audio:
                _filler_audio[key] = (result.mime, audio)
        except Exception as e:
            print(f"[voice] filler pre-render failed ({type(e).__name__}: {e})", flush=True)
            return


# In memory: a reconnect with the same sessionId continues the conversation.
conversations: dict[str, Conversation] = {}


class VoiceConnection:
    """One WebSocket connection. Reads client messages; runs each turn as a background task."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.conversation: Conversation | None = None
        self.recording: Utterance | None = None  # while the key is down
        self.turn: asyncio.Task | None = None
        self.warm_up: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()

    # ── sending ──

    async def send(self, msg: WireModel) -> None:
        await self._send(text=msg.to_json())

    async def send_bytes(self, data: bytes) -> None:
        await self._send(bytes=data)

    async def _send(self, **message) -> None:
        async with self._send_lock:
            with suppress(WebSocketDisconnect, RuntimeError):  # the client is gone: nothing to do
                if message.get("text") is not None:
                    await self.ws.send_text(message["text"])
                else:
                    await self.ws.send_bytes(message["bytes"])

    # ── receiving ──

    async def serve(self) -> None:
        await self.ws.accept()
        try:
            while True:
                frame = await self.ws.receive()
                if frame["type"] == "websocket.disconnect":
                    break
                if frame.get("bytes") is not None:
                    if self.recording:
                        self.recording.feed(frame["bytes"])
                    continue
                await self.handle_text(frame.get("text") or "")
        except WebSocketDisconnect:
            pass
        finally:
            await self.interrupt()

    async def handle_text(self, raw: str) -> None:
        try:
            msg = client_message.validate_python(json.loads(raw))
        except (json.JSONDecodeError, ValidationError):
            await self.send(VoiceErrorMessage(message="invalid JSON message"))
            return
        if not self.conversation and not isinstance(msg, StartMessage):
            await self.open()  # no "start" yet: open a fresh conversation

        match msg:
            case StartMessage(session_id=session_id, actor_name=actor_name):
                await self.interrupt()
                await self.open(session_id, actor_name)
            case AudioStartMessage(mime=mime, hint=hint):
                await self.interrupt()  # barge-in
                self.recording = Utterance(get_stt_client(), mime, hint, on_partial=self.send_partial)
            case AudioEndMessage():
                if self.recording:
                    utterance, self.recording = self.recording, None
                    self.start_turn(utterance=utterance)
            case TextMessage(text=text):
                await self.interrupt()
                self.start_turn(text=text)
            case ResetMessage():
                await self.interrupt()
                self.conversation.history = []
                await self.open(self.conversation.id)

    async def send_partial(self, update: STTUpdate) -> None:
        await self.send(TranscriptMessage(text=update.text, final=False, stable=update.stable))

    async def open(self, session_id: str | None = None, actor_name: str | None = None) -> None:
        conv = conversations.get(session_id or "") or Conversation(id=session_id or str(uuid.uuid4()))
        if actor_name:
            conv.actor_name = actor_name
        conversations[conv.id] = self.conversation = conv
        llm = get_llm_client()
        await self.send(
            ReadyMessage(session_id=conv.id, stt=get_stt_client().name, tts=get_tts_client().name, llm=f"{llm.provider}:{llm.model}")
        )
        # Fetch the company vocabulary for the STT now, not when the caller first speaks; warm the TTS with the fillers.
        self.warm_up = self.warm_up or asyncio.create_task(self._warm_up())

    async def _warm_up(self) -> None:
        await asyncio.gather(stt_hint(get_stt_client().name, None), prerender_fillers(get_tts_client()), get_meta(), warm_llm())

    def start_turn(self, **turn_input) -> None:
        self.turn = asyncio.create_task(self.run_turn(self.conversation, **turn_input))

    async def interrupt(self) -> None:
        """Barge-in: drop a recording in progress, stop the running turn and wait until it has cleaned up."""
        if self.recording:
            self.recording.cancel()
            self.recording = None
        if self.turn and not self.turn.done():
            self.turn.cancel()
            with suppress(asyncio.CancelledError):
                await self.turn
        self.turn = None

    # ── one turn ──

    async def run_turn(
        self,
        conv: Conversation,
        text: str | None = None,
        utterance: Utterance | None = None,  # spoken: already being transcribed since audio_start
    ) -> None:
        t0 = time.perf_counter()  # end of caller speech
        timings = TurnTimings()
        heard, spoken = "", ""
        step_text = ""  # what the model said since the last tool result (not yet in `working`)
        working: list[ChatMessage] | None = None
        committed = False
        speaker: Speaker | None = None
        ack: asyncio.Task | None = None
        said_first: list[str] = []  # the deadline acknowledgement, if it played (spoken before the model's text)
        try:
            # 1. Speech → text: with a streaming STT only the last words are left to finalize
            if utterance is not None:
                text = await utterance.text()
                timings.stt_ms = ms_since(t0)  # end of speech → final transcript
            heard = (text or "").strip()
            if not heard:
                # Nothing usable (noise, a mumble, Space released too early): say so out loud instead of leaving the
                # caller in silence. Not added to the history: nothing was heard.
                reprompt = REPROMPTS[conv.fillers_used % len(REPROMPTS)]
                conv.fillers_used += 1
                await self.send(TranscriptMessage(text="(inaudible)", final=True))
                await self.send(AgentTextMessage(delta=reprompt))
                speaker = Speaker(get_tts_client(), self.send, self.send_bytes)
                speaker.speak(reprompt)
                await speaker.finish()
                timings.tts_first_byte_ms = speaker.tts_first_byte_ms
                if speaker.first_byte_at:
                    timings.total_ms = int((speaker.first_byte_at - t0) * 1000 + 0.5)
                await self.send(AgentDoneMessage(text=reprompt, timings=timings))
                return
            await self.send(TranscriptMessage(text=heard, final=True))

            # 2. Agent, on a working copy of the history (committed at the end)
            working = [*conv.history, ChatMessage(role="user", content=heard)]
            speaker = Speaker(get_tts_client(), self.send, self.send_bytes, today=(await get_meta()).get("today"))
            ack = asyncio.create_task(self._ack_after(speaker, conv, said_first))
            llm_start = time.perf_counter()
            async for ev in run_agent(working, llm=get_llm_client(), tools=all_tools(), mode="voice", actor_name=conv.actor_name):
                match ev:
                    case TextEvent(delta=delta):
                        if timings.llm_first_token_ms is None:
                            timings.llm_first_token_ms = ms_since(llm_start)
                        spoken += delta
                        step_text += delta
                        await self.send(AgentTextMessage(delta=delta))
                        speaker.push(delta)
                    case ToolCallEvent(call=call):
                        if not spoken.strip() and not speaker.queued_any:  # silence while tools run: a short filler now
                            filler = FILLERS[conv.fillers_used % len(FILLERS)]
                            conv.fillers_used += 1
                            spoken += f"{filler} "
                            await self.send(AgentTextMessage(delta=f"{filler} "))
                            speaker.filler(filler)
                            if timings.llm_first_token_ms is None:
                                timings.llm_first_token_ms = ms_since(llm_start)
                        await self.send(AgentToolMessage(name=call.name, args=call.arguments))
                    case ToolResultEvent(name=name, ok=ok, ms=ms):
                        step_text = ""
                        await self.send(AgentToolMessage(name=name, ok=ok, ms=ms))
                    case ErrorEvent(message=message):
                        await self.send(VoiceErrorMessage(message=message))
            timings.llm_total_ms = ms_since(llm_start)
            conv.history = trim(working)
            committed = True

            # 3. Speak the last sentence and wait until all the audio is sent
            await speaker.finish()
            timings.tts_first_byte_ms = speaker.tts_first_byte_ms
            if speaker.first_byte_at:
                timings.total_ms = int((speaker.first_byte_at - t0) * 1000 + 0.5)
            await self.send(AgentDoneMessage(text=" ".join([*said_first, spoken.strip()]).strip(), timings=timings))

        except asyncio.CancelledError:
            # Interrupted: keep what was heard, the tool rounds already done (an order the agent created must stay
            # known) and what the agent had started to say. Not when the turn was already committed (barge-in during
            # the last sentence's audio): that would duplicate it. trim() closes a tool call cut mid-run.
            if speaker:
                await speaker.stop()
            voiced = speaker.voiced_text() if speaker else ""
            if heard and not committed:
                kept = working if working is not None else [*conv.history, ChatMessage(role="user", content=heard)]
                last = kept[-1]
                said = heard_part(step_text, voiced)
                if said and not (last.role == "assistant" and last.tool_calls):
                    kept = [*kept, ChatMessage(role="assistant", content=f"{said} …")]
                conv.history = trim(kept)
            elif committed and speaker and not speaker.done and conv.history and conv.history[-1].role == "assistant":
                # Cut while the final answer was being spoken: remember only what the caller actually heard.
                final = conv.history[-1]
                said = heard_part(final.content, voiced)
                if said != final.content.strip():
                    conv.history[-1] = final.model_copy(update={"content": f"{said} … (interrompu)" if said else "(interrompu avant de répondre)"})
            raise
        except Exception as e:
            await self.send(VoiceErrorMessage(message=str(e) or type(e).__name__))
        finally:
            if ack and not ack.done():
                ack.cancel()
            if utterance:
                utterance.cancel()  # interrupted while transcribing: close the provider stream

    async def _ack_after(self, speaker: "Speaker", conv: Conversation, said: list[str]) -> None:
        """After ACK_AFTER_S, if the agent has said nothing yet (no text, nothing queued), play an acknowledgement."""
        await asyncio.sleep(ACK_AFTER_S)
        if speaker.queued_any or speaker.text_seen:
            return
        phrase = FIRST_ACK if not conv.history else ACKS[conv.fillers_used % len(ACKS)]
        conv.fillers_used += 1
        said.append(phrase)
        speaker.filler(phrase)
        await self.send(AgentTextMessage(delta=f"{phrase} "))


class Speaker:
    """Buffers the streamed text, cuts it into sentences and speaks them in order, as one audio segment."""

    # a sentence ends with . ! ? … followed by a space ("18.50" is not a boundary)
    SENTENCE = re.compile(r"^([\s\S]*?[.!?…])\s+")
    # the FIRST chunk of a reply may end at a comma / colon once it is long enough: first sound sooner
    FIRST_CLAUSE = re.compile(r"^([\s\S]{28,}?[,;:])\s+")

    def __init__(
        self,
        tts: TTSClient,
        send: Callable[[WireModel], Awaitable],
        send_bytes: Callable[[bytes], Awaitable],
        today: str | None = None,  # the ERP's business date, for « demain » in spoken dates
    ):
        self.tts, self.send, self.send_bytes, self.today = tts, send, send_bytes, today
        self.buffer = ""
        # queued items: (text as written, audio source): a str to synthesise, or pre-rendered (mime, bytes)
        self.sentences: asyncio.Queue[tuple[str, str | tuple[str, bytes], bool] | None] = asyncio.Queue()
        self.worker: asyncio.Task | None = None  # speaks the queued sentences one after the other
        self.started = False
        self.done = False  # all the audio was sent
        self.queued_any = False
        self.text_seen = False  # the model started its answer (the deadline acknowledgement must not cut in)
        self.voiced: list[tuple[str, bool]] = []  # (text, is_filler) whose audio started playing
        self.first_byte_at: float | None = None
        self.tts_first_byte_ms: int | None = None

    def push(self, delta: str) -> None:
        self.text_seen = self.text_seen or bool(delta.strip())
        self.buffer += delta
        if not self.queued_any and (m := self.FIRST_CLAUSE.match(self.buffer)) and not self.SENTENCE.match(self.buffer):
            self.speak(m[1])
            self.buffer = self.buffer[m.end() :]
        while m := self.SENTENCE.match(self.buffer):
            self.speak(m[1])
            self.buffer = self.buffer[m.end() :]

    def speak(self, sentence: str) -> None:
        if not sentence.strip():
            return
        spoken = to_speech(sentence, self.today) or sentence
        self._queue((sentence.strip(), spoken, False))

    def filler(self, text: str) -> None:
        """A waiting phrase: the pre-rendered audio if there is one, else synthesised like any sentence."""
        audio = _filler_audio.get((self.tts.name, settings.tts.voice or None, text))
        self._queue((text, audio or text, True))

    def _queue(self, item: tuple[str, str | tuple[str, bytes], bool]) -> None:
        self.queued_any = True
        if self.worker is None:
            self.worker = asyncio.create_task(self._speak_queued())
        self.sentences.put_nowait(item)

    def voiced_text(self, fillers: bool = False) -> str:
        return " ".join(text for text, is_filler in self.voiced if fillers or not is_filler)

    async def finish(self) -> None:
        """Speak what is left in the buffer, wait for all the audio, close the segment."""
        self.speak(self.buffer)
        self.buffer = ""
        if self.worker:
            self.sentences.put_nowait(None)
            await self.worker
        self.done = True
        if self.started:
            await self.send(AgentAudioEndMessage())

    async def stop(self) -> None:
        """Interrupted: drop the queued sentences, close the segment if audio was sent."""
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
        if self.started:
            await self.send(AgentAudioEndMessage())

    async def _speak_queued(self) -> None:
        while (item := await self.sentences.get()) is not None:
            text, source, is_filler = item
            tts_start = time.perf_counter()
            try:
                if isinstance(source, tuple):  # pre-rendered filler: no TTS round-trip at all
                    mime, audio = source
                    await self._audio_start(mime, tts_start)
                    self.voiced.append((text, is_filler))
                    await self.send_bytes(audio)
                    continue
                result = await self.tts.synthesize(source, settings.tts.voice or None)
                # aclosing: on barge-in (cancellation) the provider's HTTP stream is closed right away
                first = True
                async with aclosing(result.chunks) as chunks:  # type: ignore[type-var]
                    async for chunk in chunks:
                        if first:
                            first = False
                            await self._audio_start(result.mime, tts_start)
                            self.voiced.append((text, is_filler))
                        await self.send_bytes(chunk)
            except Exception as e:
                await self.send(VoiceErrorMessage(message=f"TTS : {e}"))

    async def _audio_start(self, mime: str, tts_start: float) -> None:
        if not self.started:
            self.started = True
            await self.send(AgentAudioStartMessage(mime=mime))
            self.first_byte_at = time.perf_counter()
            self.tts_first_byte_ms = ms_since(tts_start)


def heard_part(text: str, voiced: str) -> str:
    """The beginning of `text` the caller actually heard: its sentences found in what was voiced, up to the first
    one that was not (the rest was generated but cut by the barge-in)."""
    out = []
    for sentence in re.split(r"(?<=[.!?…,;:])\s+", (text or "").strip()):
        if sentence and sentence in voiced:
            out.append(sentence)
        else:
            break
    return " ".join(out)


def trim(history: list[ChatMessage], max_messages: int = 40) -> list[ChatMessage]:
    """Keep the last ~40 messages, starting on a user message (never split a tool call from its result)."""
    history = sanitize_history(history)  # no dangling tool call (cancelled mid-tool), no orphan result
    if len(history) <= max_messages:
        return history
    start = next((i for i, m in enumerate(history) if i >= len(history) - max_messages and m.role == "user"), -1)
    return history[start:] if start > 0 else history

