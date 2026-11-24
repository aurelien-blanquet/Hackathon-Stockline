"""Timing regression tests (latency diagnosis): every stage of a voice turn is measured, the acknowledgement is kept
apart from the useful answer, and the browser is told where the useful audio starts."""

import asyncio
import json

import pytest
from test_history_pairing import ScriptedLLM

from app.clients import LLMText, LLMToolCall
from app.clients.base import STTClient, STTUpdate
from app.clients.mock_speech import MockTTS
from app.schemas import ToolCall
from app.services import utterance as utterance_mod
from app.services import voice_session
from app.services.utterance import Utterance
from app.tools.registry import Tool, ToolArgs


class FakeStreamingSTT(STTClient):
    """Live STT: connects after `connect_s`, finalizes `finalize_s` after the end of audio; `hang` = never finalizes."""

    name, streams = "fake", True

    def __init__(self, connect_s=0.0, finalize_s=0.0, hang=False):
        self.connect_s, self.finalize_s, self.hang = connect_s, finalize_s, hang
        self.transcribed_whole = False

    async def transcribe(self, audio, mime, hint=None):
        self.transcribed_whole = True
        return "texte complet"

    async def transcribe_stream(self, audio, mime, hint=None):
        await asyncio.sleep(self.connect_s)
        async for _ in audio:
            pass
        if self.hang:
            await asyncio.sleep(10)
        await asyncio.sleep(self.finalize_s)
        yield STTUpdate("bonjour", final=True, stable="bonjour")


async def record(stt, frames=3, speak_s=0.0):
    async def no_partial(update):
        pass

    u = Utterance(stt, "audio/webm", None, on_partial=no_partial)
    for _ in range(frames):
        u.feed(b"x")
    await asyncio.sleep(speak_s)
    return u, await u.text()


# ── speech-to-text stages ──



@pytest.fixture(autouse=True)
def no_vocabulary(monkeypatch):
    """The vocabulary comes from the ERP (cached): not what these tests measure."""

    async def hint(stt_name, hint):
        return hint

    monkeypatch.setattr(utterance_mod, "stt_hint", hint)


async def test_stt_stages_are_timestamped_in_order():
    u, text = await record(FakeStreamingSTT(finalize_s=0.05), speak_s=0.02)
    assert text == "bonjour" and not u.fallback
    assert u.started_at <= u.stream_ready_at <= u.ended_at <= u.finalize_sent_at <= u.final_at
    assert u.final_at - u.finalize_sent_at >= 0.045  # the provider's finalize time is visible on its own


async def test_slow_stream_opening_shows_up_as_connect_time_and_backlog():
    # the caller talks for 20 ms but the provider stream needs 80 ms to open: frames wait in the queue
    u, _ = await record(FakeStreamingSTT(connect_s=0.08), frames=5, speak_s=0.02)
    assert u.stream_ready_at - u.started_at >= 0.075
    assert u.backlog_frames == 5


async def test_fallback_is_flagged_and_still_transcribes(monkeypatch):
    monkeypatch.setattr(utterance_mod, "FINAL_TIMEOUT_S", 0.05)
    stt = FakeStreamingSTT(hang=True)
    u, text = await record(stt)
    assert u.fallback and stt.transcribed_whole and text == "texte complet"  # reliability fallback kept


async def test_stt_timings_go_into_turn_timings():
    u, _ = await record(FakeStreamingSTT(connect_s=0.03, finalize_s=0.04), frames=2)
    t = voice_session.TurnTimings()
    voice_session.stt_timings(t, u.ended_at, u)
    assert t.stt_connect_ms >= 25 and t.stt_backlog_frames == 2 and t.stt_fallback is False
    assert 0 <= t.stt_finalize_sent_ms < 40  # sent right away: the 40 ms are the provider's finalize


# ── acknowledgement vs useful answer ──


class WireWS:
    """Records the order of what is sent: ("text", message type) and ("bytes", n)."""

    def __init__(self):
        self.sent, self.order = [], []

    async def send_text(self, text):
        m = json.loads(text)
        self.sent.append(m)
        self.order.append(("text", m["type"]))

    async def send_bytes(self, data):
        self.order.append(("bytes", len(data)))


class SlowLLM(ScriptedLLM):
    async def stream(self, request):
        await asyncio.sleep(0.15)  # slower than the acknowledgement deadline
        async for ev in super().stream(request):
            yield ev


def turn_session(monkeypatch, llm, tools=()):
    async def none(*a, **k):
        return None

    async def meta():
        return {"today": "2026-11-24"}

    monkeypatch.setattr(voice_session, "fast_confirm", none)
    monkeypatch.setattr(voice_session, "preload", none)
    monkeypatch.setattr(voice_session, "get_meta", meta)
    monkeypatch.setattr(voice_session, "get_llm_client", lambda: llm)
    monkeypatch.setattr(voice_session, "get_tts_client", lambda: MockTTS())
    monkeypatch.setattr(voice_session, "all_tools", lambda: list(tools))
    monkeypatch.setattr(voice_session, "ACK_AFTER_S", 0.03)
    monkeypatch.setattr(voice_session, "_filler_audio", {})
    return voice_session.VoiceConnection(WireWS()), voice_session.Conversation(id="t")


def done_timings(session):
    return next(m for m in session.ws.sent if m["type"] == "agent_done")["timings"]


async def test_ack_and_useful_answer_are_measured_apart(monkeypatch):
    session, conv = turn_session(monkeypatch, SlowLLM([[LLMText("Bonjour Mélanie, c'est noté.")]]))
    await session.run_turn(conv, text="bonjour")
    t = done_timings(session)
    assert t["ackAudioMs"] < t["usefulTextMs"] <= t["usefulAudioMs"]
    assert t["totalMs"] == t["ackAudioMs"]  # « Total » is the first sound, i.e. the acknowledgement here
    assert t["usefulTextMs"] >= 140  # the model's 150 ms, not the acknowledgement's 30 ms


async def test_mark_sits_between_ack_audio_and_useful_audio(monkeypatch):
    session, conv = turn_session(monkeypatch, SlowLLM([[LLMText("Bonjour Mélanie, c'est noté.")]]))
    await session.run_turn(conv, text="bonjour")
    order = session.ws.order
    start, mark = order.index(("text", "agent_audio_start")), order.index(("text", "agent_audio_mark"))
    assert any(kind == "bytes" for kind, _ in order[start:mark])  # acknowledgement audio first
    assert order[mark + 1][0] == "bytes"  # then the useful audio, right after the mark
    assert order.count(("text", "agent_audio_mark")) == 1


async def test_fast_answer_marks_the_first_audio_as_useful(monkeypatch):
    session, conv = turn_session(monkeypatch, ScriptedLLM([[LLMText("C'est noté.")]]))
    await session.run_turn(conv, text="cinq kilos de tomme")
    t = done_timings(session)
    assert t.get("ackAudioMs") is None and t["usefulAudioMs"] == t["totalMs"]
    order = session.ws.order
    assert order.index(("text", "agent_audio_mark")) == order.index(("text", "agent_audio_start")) + 1


async def test_tool_calls_are_timed(monkeypatch):
    async def slow_tool(ctx):
        await asyncio.sleep(0.05)
        return {"ok": True}

    tool = Tool(name="lookup", description="x", args_model=ToolArgs, fn=slow_tool)
    llm = ScriptedLLM([[LLMToolCall(ToolCall(id="c1", name="lookup", arguments={}))], [LLMText("Il en reste.")]])
    session, conv = turn_session(monkeypatch, llm, [tool])
    await session.run_turn(conv, text="il reste du beaufort ?")
    t = done_timings(session)
    (timing,) = t["tools"]
    assert timing["name"] == "lookup" and timing["ms"] >= 45
    assert timing["startMs"] + timing["ms"] <= t["usefulTextMs"] + 2  # the answer came after the tool (ms rounding)
    assert t["ackAudioMs"] < t["usefulAudioMs"]  # « Je regarde. » before the answer


async def test_fast_confirm_is_timed_without_model(monkeypatch):
    from app.services.fast_path import Injected

    session, conv = turn_session(monkeypatch, ScriptedLLM([]))

    async def fast(working, erp, today):
        call = ToolCall(id="f1", name="confirm_order", arguments={"orderId": "ord_1"})
        return Injected(messages=[], calls=[(call, {}, 12)], reply="Parfait, c'est validé.")

    monkeypatch.setattr(voice_session, "fast_confirm", fast)
    await session.run_turn(conv, text="oui")
    t = done_timings(session)
    assert t["tools"][0]["name"] == "confirm_order" and t["tools"][0]["ms"] == 12
    assert t["usefulTextMs"] < 30 and t.get("llmFirstTokenMs") is None


async def test_stt_probe_measures_the_finalize_after_the_end_of_speech(monkeypatch):
    from app import stt_probe

    monkeypatch.setattr(stt_probe, "CHUNK_S", 0.01)
    r = await stt_probe.one_run(FakeStreamingSTT(finalize_s=0.06), b"x" * 4000, None)
    assert r["text"] == "bonjour" and 55 <= r["finalize"] < 200 and r["connect"] is not None
