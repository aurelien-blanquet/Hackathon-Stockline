"""Natural speech guards in the voice session (DECISIONS §5, mar 01:55 — defects seen in real runs):
- the recap is said once: after a clean write (no warning), text the model adds is neither voiced nor shown;
- the model narrating its reasoning (« … son habituel, donc je fais répéter ») is never voiced."""

import pytest
from test_history_pairing import FakeWS, ScriptedLLM

from app.clients import LLMText, LLMToolCall
from app.clients.mock_speech import MockTTS
from app.schemas import ToolCall
from app.services import voice_session
from app.tools.registry import Tool, ToolArgs


class RecordingTTS(MockTTS):
    name = "recording"

    def __init__(self):
        self.texts: list[str] = []

    async def synthesize(self, text, voice=None):
        self.texts.append(text)
        return await super().synthesize(text, voice)


def session_with(monkeypatch, steps, tts, result):
    async def no_fast_path(*args, **kwargs):
        return None

    async def create_draft_order(ctx):
        return result

    async def lookup(ctx):
        return {"ok": True}

    tools = [Tool(name="create_draft_order", description="x", args_model=ToolArgs, fn=create_draft_order),
             Tool(name="lookup", description="x", args_model=ToolArgs, fn=lookup)]
    monkeypatch.setattr(voice_session, "fast_confirm", no_fast_path)
    monkeypatch.setattr(voice_session, "preload", no_fast_path)
    monkeypatch.setattr(voice_session, "get_llm_client", lambda: ScriptedLLM(steps))
    monkeypatch.setattr(voice_session, "all_tools", lambda: tools)
    monkeypatch.setattr(voice_session, "get_tts_client", lambda: tts)
    monkeypatch.setattr(voice_session, "_filler_audio", {})
    monkeypatch.setattr(voice_session, "ACK_AFTER_S", 30)  # no deadline acknowledgement in these tests
    return voice_session.VoiceConnection(FakeWS()), voice_session.Conversation(id="t")


def call(name, id="a"):
    return LLMToolCall(ToolCall(id=id, name=name, arguments={}))


RECAP = "Vingt reblochons laitiers, livraison vendredi. Je valide ? "
AGAIN = "Pour récapituler : vingt reblochons laitiers, livraison vendredi vingt-sept novembre. Je valide ?"


def done(session):
    return next(m for m in reversed(session.ws.sent) if m["type"] == "agent_done")


def shown(session):
    return "".join(m["delta"] for m in session.ws.sent if m["type"] == "agent_text")


async def test_recap_is_said_once_after_a_clean_write(monkeypatch):
    tts = RecordingTTS()
    session, conv = session_with(monkeypatch, [[LLMText(RECAP), call("create_draft_order")], [LLMText(AGAIN)]], tts,
                                 {"id": "ord_1", "warnings": []})
    await session.run_turn(conv, text="vingt reblochons laitiers pour vendredi")
    assert tts.texts == ["Vingt reblochons laitiers, livraison vendredi.", "Je valide ?"]
    assert done(session)["text"] == RECAP.strip()
    assert "Pour récapituler" not in shown(session)


async def test_an_erp_warning_after_the_write_is_still_said(monkeypatch):
    tts = RecordingTTS()
    warn = "Attention, il n'en reste que douze en stock."
    session, conv = session_with(monkeypatch, [[LLMText(RECAP), call("create_draft_order")], [LLMText(warn)]], tts,
                                 {"id": "ord_1", "warnings": [{"code": "stock_short"}]})
    await session.run_turn(conv, text="vingt reblochons laitiers pour vendredi")
    assert tts.texts[-1] == warn and done(session)["text"].endswith(warn)


async def test_a_warned_write_voices_the_warning_not_the_recap_again(monkeypatch):
    # s11, mar 03:27: the lot expires before delivery; the model re-read the whole recap around the warning (451 chars)
    tts = RecordingTTS()
    again = ("Le brouillon est créé : dix kilos de diots et six kilos de raclette tranchée, livraison samedi. "
             "Attention, le lot de diots expire vendredi, avant la livraison. Je valide la commande ?")
    session, conv = session_with(monkeypatch, [[LLMText(RECAP), call("create_draft_order")], [LLMText(again)]], tts,
                                 {"id": "ord_1", "warnings": [{"code": "lot_expires"}]})
    await session.run_turn(conv, text="dix kilos de diots et six de raclette tranchée pour samedi")
    assert tts.texts[-1] == "Attention, le lot de diots expire vendredi, avant la livraison."
    assert "Le brouillon est créé" not in done(session)["text"] and "Je valide la commande" not in done(session)["text"]


@pytest.mark.parametrize("text,kept", [
    ("C'est noté. Il n'en reste que douze en stock. Je valide ?", ["Il n'en reste que douze en stock."]),
    ("Le brouillon est créé. Vous préférez livrer jeudi ?", ["Vous préférez livrer jeudi ?"]),
    ("Le brouillon est créé, total cent euros. Je valide ?", []),
])
def test_worth_saying_after_write(text, kept):
    assert voice_session.worth_saying_after_write(text) == kept


async def test_without_a_question_before_the_write_the_answer_after_it_is_said(monkeypatch):
    tts = RecordingTTS()
    after = "C'est modifié : quinze kilos d'abondance. Je valide ?"
    session, conv = session_with(monkeypatch, [[call("create_draft_order")], [LLMText(after)]], tts, {"id": "ord_1"})
    await session.run_turn(conv, text="plutôt quinze")
    assert done(session)["text"].endswith(after)


async def test_a_read_tool_never_silences_the_answer(monkeypatch):
    tts = RecordingTTS()
    answer = "Il reste douze kilos de tomme."
    session, conv = session_with(monkeypatch, [[LLMText("Je regarde ça, d'accord ? "), call("lookup")], [LLMText(answer)]], tts, {})
    await session.run_turn(conv, text="il reste de la tomme ?")
    assert done(session)["text"].endswith(answer)


@pytest.mark.parametrize("text,voiced", [
    ("Vingt kilos, c'est nettement plus que son habituel, donc je fais répéter avant d'enregistrer. Antoine, tu confirmes vingt kilos ?",
     ["Antoine, tu confirmes vingt kilos ?"]),
    ("Vendredi est le 27 novembre, un jour de livraison du client. Bonjour Mélanie !", ["Bonjour Mélanie !"]),
    ("Il y a déjà une commande pour demain. Je vérifie son contenu avant d'en créer une autre. Tu la gardes ?",
     ["Il y a déjà une commande pour demain.", "Tu la gardes ?"]),
    ("Je modifie la ligne existante. C'est fait, les diots passent à dix-neuf kilos.", ["C'est fait, les diots passent à dix-neuf kilos."]),
    ("Bonjour Jean-Marc ! Je te mets ta commande habituelle ?", ["Bonjour Jean-Marc !", "Je te mets ta commande habituelle ?"]),
])
async def test_reasoning_out_loud_is_not_voiced(monkeypatch, text, voiced):
    tts = RecordingTTS()
    session, conv = session_with(monkeypatch, [[LLMText(text)]], tts, {})
    await session.run_turn(conv, text="…")
    assert [t for t in tts.texts if t] == [voice_session.to_speech(v) or v for v in voiced]
    assert done(session)["text"] == " ".join(voiced)
    assert conv.history[-1].content == text  # the model's own words stay in its history
