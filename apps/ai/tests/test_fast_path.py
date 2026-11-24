"""services/fast_path.py: confirm without the model, preload the caller and products, never on doubtful input."""

import json

import httpx
import pytest
from test_history_pairing import FakeWS, ScriptedLLM

from app.clients.mock_speech import MockTTS
from app.schemas import ChatMessage, ToolCall
from app.services import fast_path, voice_session
from app.services.fast_path import fast_confirm, name_was_said, pending_draft, products_said, who_segments
from app.tools import ErpClient
from app.tools import voice as voice_tools

TODAY = "2026-11-24"
DRAFT = {
    "id": "ord_9", "number": "CMD-2026-000009", "status": "draft", "client": {"name": "Le Panier Savoyard"},
    "deliveryDate": "2026-11-25", "totalHt": 37.6, "warnings": [],
    "lines": [{"id": "lin_1", "productId": "prd_0001", "productName": "Reblochon de Savoie AOP fermier (450 g)", "qty": 4, "unit": "piece", "unitPrice": 9.4, "available": 800}],  # fmt: skip
}  # fmt: skip


def history(draft=DRAFT, answer="Ouais vas-y", recap="Quatre reblochons fermiers, livraison demain. Je valide ?", card=None):
    call = ToolCall(id="c1", name="create_draft_order", arguments={"clientId": "cli_0027"})
    msgs = [ChatMessage(role="user", content="c'est Jean-Marc, quatre reblochons fermiers")]
    if card is not None:
        msgs += [
            ChatMessage(role="assistant", content="", tool_calls=[ToolCall(id="c0", name="identify_caller", arguments={"who": "x"})]),
            ChatMessage(role="tool", tool_call_id="c0", name="identify_caller", content=json.dumps(card)),
        ]
    msgs += [
        ChatMessage(role="assistant", content=recap, tool_calls=[call]),
        ChatMessage(role="tool", tool_call_id="c1", name="create_draft_order", content=json.dumps(draft)),
        ChatMessage(role="user", content=answer),
    ]
    return msgs


@pytest.fixture
def erp():
    requests = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests.append((req.method, req.url.path))
        if req.url.path == "/api/orders/ord_9/confirm":
            return httpx.Response(200, json={**DRAFT, "status": "confirmed"})
        return httpx.Response(404, json={"error": {"message": "no"}})

    client = ErpClient("voice_agent", base_url="http://erp", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client.requests = requests  # type: ignore[attr-defined]
    return client


@pytest.fixture(autouse=True)
def today(monkeypatch):
    async def _today():
        return TODAY

    monkeypatch.setattr(voice_tools, "_today", _today)


# ── confirm without the model ──


async def test_yes_after_recap_confirms_in_code(erp):
    fast = await fast_confirm(history(), erp, TODAY)
    assert erp.requests == [("POST", "/api/orders/ord_9/confirm")]
    assert fast.reply == "Parfait, c'est validé, livraison demain. Merci, bonne journée !"
    assert [m.role for m in fast.messages] == ["assistant", "tool", "assistant"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"answer": "Oui mais enlève le reblochon"},  # a correction
        {"answer": "non attends"},
        {"answer": "oui c'est bon, et rajoute aussi deux kilos de tomme pour la semaine prochaine stp"},  # says more
        {"draft": {**DRAFT, "warnings": [{"code": "credit_limit", "message": "Encours au-delà du plafond"}]}},
        {"draft": {**DRAFT, "status": "confirmed"}},  # nothing pending
        {"recap": "Je regarde.", "answer": "oui"},  # no recap: a yes to what?
        {"card": {"found": True, "client": {"id": "cli_0007"}, "blocked": "Client BLOQUÉ"}},
    ],
)
async def test_anything_doubtful_goes_to_the_model(erp, kwargs):
    assert await fast_confirm(history(**kwargs), erp, TODAY) is None
    assert erp.requests == []  # nothing confirmed


def test_pending_draft_is_the_latest_order_result():
    h = history()
    assert pending_draft(h)["id"] == "ord_9"
    confirmed = ChatMessage(role="tool", tool_call_id="c9", name="confirm_order", content=json.dumps({**DRAFT, "status": "confirmed"}))
    assert pending_draft([*h, confirmed]) is None


async def test_voice_turn_confirms_without_any_model_call(monkeypatch, erp):
    llm = ScriptedLLM([])
    monkeypatch.setattr(voice_session, "get_llm_client", lambda: llm)
    monkeypatch.setattr(voice_session, "get_tts_client", lambda: MockTTS())
    monkeypatch.setattr(voice_session, "ErpClient", lambda *a, **k: erp)

    async def meta():  # the ERP's business date, without depending on a running ERP
        return {"today": TODAY}

    monkeypatch.setattr(voice_session, "get_meta", meta)
    session, conv = voice_session.VoiceConnection(FakeWS()), voice_session.Conversation(id="t")
    conv.history = history()[:-1]
    await session.run_turn(conv, text="ouais vas-y")
    assert llm.requests == []  # no model call at all
    done = next(m for m in session.ws.sent if m["type"] == "agent_done")
    assert done["text"] == "Parfait, c'est validé, livraison demain. Merci, bonne journée !"
    assert conv.history[-1].content == done["text"]


# ── preload: what was said ──

INDEX = sorted(
    ((tuple(fast_path._words(p)), p) for p in ["reblochon", "reblochon laitier", "reblochon fermier", "tomme", "tomme de Savoie", "diots", "beaufort d'été"]),
    key=lambda x: -len(x[0]),
)


def test_products_said_longest_first_plural_and_accents():
    assert products_said("Mets-moi vingt reblochons laitiers et de la tomme", INDEX) == ["reblochon laitier", "tomme"]
    assert products_said("il vous reste du beaufort d'ete ?", INDEX) == ["beaufort d'été"]
    assert products_said("trois kilos de diots et deux tommes de Savoie", INDEX) == ["diots", "tomme de Savoie"]
    assert products_said("je voudrais passer une commande", INDEX) == []


def test_who_segments():
    assert who_segments("Salut, c'est Mélanie de la Balme. Mets-moi vingt reblochons.")[0] == "Mélanie de la Balme"
    assert "Bonjour, Le Petit Lac" in who_segments("Bonjour, Le Petit Lac. Vous me mettez dix reblochons ?")


def card(name, contacts):
    return {"found": True, "client": {"id": "x", "name": name, "contacts": [{"name": c} for c in contacts]}}


def test_a_client_is_injected_only_if_its_name_was_said():
    assert name_was_said(card("Le Panier Savoyard du Grand-Bornand", ["Jean-Marc Dupraz"]), "c'est Jean-Marc du Panier Savoyard du Grand-Bornand")
    assert name_was_said(card("Le Chalet de la Balme", ["Mélanie Thovex"]), "c'est Mélanie de la Balme")  # half + contact
    # a colleague « Julien au dépôt » is not the client whose contact is called Julien
    assert not name_was_said(card("Le Chalet de Mireille", ["Julien Favre"]), "C'est Julien au dépôt, il reste du persillé ?")
    assert not name_was_said(card("Le Chalet de la Balme", ["Raymond Thovex"]), "c'est la Balme")  # half, no contact


def test_voice_requests_turn_thinking_off_only_where_the_api_accepts_it():
    from app.clients import LLMRequest
    from app.clients.anthropic import AnthropicLLM

    req = LLMRequest(system="s", messages=[ChatMessage(role="user", content="x")], thinking="disabled")
    assert AnthropicLLM("claude-haiku-5-5", "k", effort="low").build_body(req)["thinking"] == {"type": "disabled"}
    assert "thinking" not in AnthropicLLM("claude-haiku-5-5", "k", effort="xhigh").build_body(req)  # 400 there
    assert "thinking" not in AnthropicLLM("claude-haiku-5-5", "k", effort="low").build_body(LLMRequest(system="s", messages=req.messages))


async def test_agent_loop_sends_thinking_off_in_voice_mode_only():
    from app.agent import run_agent

    seen = []

    class Spy(ScriptedLLM):
        async def stream(self, request):
            seen.append(request.thinking)
            async for ev in super().stream(request):
                yield ev

    for mode in ("voice", "chat"):
        async for _ in run_agent([ChatMessage(role="user", content="x")], llm=Spy([]), tools=[], mode=mode):
            pass
    assert seen == ["disabled", None]


@pytest.mark.parametrize(
    "model,effort,expected",
    [
        ("claude-haiku-5-5", "low", {"type": "disabled"}),
        ("claude-sonnet-5-5", "low", {"type": "between_tools"}),  # Sonnet 5.5 rejects "disabled" with a 400
        ("claude-sonnet-5-5", "xhigh", None),
        ("claude-opus-5-5", "low", None),  # cannot be turned off
        ("claude-sonnet-5", "medium", {"type": "disabled"}),
        ("claude-haiku-4-5", "low", None),
    ],
)
def test_thinking_off_per_model(model, effort, expected):
    from app.clients.anthropic import thinking_off

    assert thinking_off(model, effort) == expected
