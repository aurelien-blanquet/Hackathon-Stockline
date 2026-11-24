"""/voice reliability: the yes is bound to the latest recap; a cut write is reconciled with the ERP; the caller only
hears CUSTOMER text (services/customer_text.py)."""

import json

import pytest

from app.agent.guardrails import may_confirm
from app.agent.sanitize import INTERRUPTED
from app.schemas import ChatMessage, ToolCall
from app.services import fast_path
from app.services.customer_text import CustomerGate


def a(text="", calls=None):
    return ChatMessage(role="assistant", content=text, tool_calls=calls or None)


def u(text):
    return ChatMessage(role="user", content=text)


def tool(call_id, name, result):
    return ChatMessage(role="tool", tool_call_id=call_id, name=name, content=result if isinstance(result, str) else json.dumps(result))


DRAFT = ToolCall(id="d1", name="create_draft_order", arguments={"clientId": "cli_0027", "lines": [{"productId": "prd_0004", "qty": 8}]})
RECAP = "Huit kilos de tomme de Savoie, livrés demain. Je valide ?"


# ── confirmation ──


def test_yes_to_the_recap_confirms():
    assert may_confirm([u("8 kg de tomme"), a(RECAP, [DRAFT]), tool("d1", DRAFT.name, {"id": "ord_1"}), u("oui")], "voice")


def test_yes_to_a_two_question_turn_does_not_confirm():  # baseline v05: « Combien ? Et je valide la tomme ? » → « Oui. »
    h = [u("8 kg de tomme"), a(RECAP, [DRAFT]), tool("d1", DRAFT.name, {"id": "ord_1"}), u("tu as de la raclette ?"),
         a("Oui, à seize euros quarante le kilo. Combien en voulez-vous ? Et je valide les huit kilos de tomme ?"), u("Oui.")]  # fmt: skip
    assert not may_confirm(h, "voice")


def test_yes_to_an_availability_question_after_a_recap_does_not_confirm():
    h = [u("8 kg de tomme"), a(RECAP, [DRAFT]), tool("d1", DRAFT.name, {"id": "ord_1"}), u("et du beaufort ?"),
         a("Oui, il nous en reste. Il vous en faut ?"), u("oui")]  # fmt: skip
    assert not may_confirm(h, "voice")


def test_yes_after_a_change_without_a_new_recap_does_not_confirm():
    upd = ToolCall(id="u1", name="update_order_line", arguments={"orderId": "ord_1", "productId": "prd_0004", "qty": 6})
    h = [u("8 kg de tomme"), a(RECAP, [DRAFT]), tool("d1", DRAFT.name, {"id": "ord_1"}), a("", [upd]), tool("u1", upd.name, {"id": "ord_1"}), u("oui")]  # fmt: skip
    assert not may_confirm(h, "voice")


def test_interrupted_recap_does_not_confirm():
    h = [u("8 kg de tomme"), a("Huit kilos de tomme de Savoie, livrés … (interrompu)", [DRAFT]), tool("d1", DRAFT.name, {"id": "ord_1"}), u("oui")]  # fmt: skip
    assert not may_confirm(h, "voice")


@pytest.mark.parametrize("said", ["oui mais mets-en douze", "oui, enlève la tomme", "non attends"])
def test_yes_but_is_a_correction(said):
    assert not may_confirm([u("8 kg de tomme"), a(RECAP, [DRAFT]), tool("d1", DRAFT.name, {"id": "ord_1"}), u(said)], "voice")


def test_chat_mode_is_unchanged():
    assert may_confirm([a("Votre commande : 3 kilos de tomme. Combien de raclette ? Je confirme ?"), u("oui")], "chat")


# ── reconciliation of a cut write ──


class FakeErp:
    def __init__(self, orders):
        self.orders, self.calls = orders, []

    async def get(self, path, query=None):
        self.calls.append((path, query))
        if path == "/api/orders":
            return [o for o in self.orders if o["clientId"] == query["clientId"]]
        return next(o for o in self.orders if path.endswith(o["id"]))


ORDER = {"id": "ord_9", "number": "CMD-2026-009999", "clientId": "cli_0027", "status": "draft", "source": "voice_agent",
         "deliveryDate": "2026-11-25", "lines": [{"id": "lin_1", "productId": "prd_0004", "productName": "Tomme de Savoie IGP", "qty": 8, "unit": "kg", "unitPrice": 15.5}],
         "totalHt": 124.0}  # fmt: skip


async def test_cut_create_is_replaced_by_the_order_the_erp_has(monkeypatch):
    async def today():
        return "2026-11-24"

    monkeypatch.setattr("app.tools.voice._today", today)
    h = [u("8 kg de tomme"), a(RECAP, [DRAFT]), tool("d1", DRAFT.name, INTERRUPTED)]
    out = await fast_path.reconcile_interrupted(h, FakeErp([ORDER]))
    r = json.loads(out[-1].content)
    assert r["reconciled"] and r["id"] == "ord_9" and "Ne la recrée pas" in r["note"]
    assert out[:2] == h[:2]  # nothing else touched


async def test_cut_create_that_never_reached_the_erp_says_so():
    h = [u("8 kg de tomme"), a(RECAP, [DRAFT]), tool("d1", DRAFT.name, INTERRUPTED)]
    r = json.loads((await fast_path.reconcile_interrupted(h, FakeErp([])))[-1].content)
    assert r["written"] is False and r["erpChecked"]


# ── INTERNAL vs CUSTOMER ──


def _run(chunks, call=None):
    g = CustomerGate()
    said = "".join(g.push(c) for c in chunks) + (g.tool_call(call) if call else "") + g.finish()
    return said, g.internal


def test_preamble_before_a_lookup_is_never_said():
    said, internal = _run(["Je vérifie le reblochon ", "et les alternatives."], "find_product")
    assert said == "" and internal == ["Je vérifie le reblochon et les alternatives."]


def test_bracketed_notes_are_never_said_even_split_across_deltas():
    said, internal = _run(["[le client ", "veut 6 kg] Ça marche, six kilos. ", "Je valide ?"], "update_order_line")
    assert said.strip() == "Ça marche, six kilos. Je valide ?" and internal == ["le client veut 6 kg"]


def test_question_is_released_at_once():
    g = CustomerGate()
    assert g.push("Le fermier ou le laitier ?") == "Le fermier ou le laitier ?"


def test_a_lone_statement_waits_for_the_end_of_the_step():
    g = CustomerGate()
    assert g.push("Je regarde le stock. ") == ""
    assert g.tool_call("find_product") == ""


def test_greeting_before_a_lookup_is_kept():
    said, internal = _run(["Bonjour Jean-Marc ! Je regarde votre commande."], "get_order")
    assert said.strip() == "Bonjour Jean-Marc !" and internal == ["Je regarde votre commande."]


# ── spoken French (values never change) ──


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("14,50 €/kg", "quatorze euros cinquante le kilo"),
        ("2,5 kg", "deux kilos et demi"),
        ("500 g", "cinq cents grammes"),
        ("Total : 1 234,56 € HT.", "Total : mille deux cent trente-quatre euros cinquante-six hors taxes."),
        ("2 000 pièces", "deux mille pièces"),
        ("Livraison le 26/11.", "Livraison le jeudi vingt-six novembre."),
        ("75 cl de mondeuse", "soixante-quinze centilitres de mondeuse"),
        ("le 31/02", "le 31/02"),  # not a date: left as written
    ],
)
def test_spoken_french(text, spoken):
    from app.agent.speak_fr import to_speech

    assert to_speech(text, "2026-11-24") == spoken


# ── next sentence rendered while the current one streams, order kept ──


def test_next_sentence_is_rendered_while_the_current_one_streams():
    import asyncio

    from app.clients.base import TTSResult
    from app.services import voice_session

    starts: dict[str, float] = {}

    class SlowTTS:
        name = "slow"

        async def synthesize(self, text, voice=None):
            starts[text] = asyncio.get_running_loop().time()

            async def chunks():
                for i in range(3):
                    await asyncio.sleep(0.05)
                    yield f"{text}|{i}".encode()

            return TTSResult("audio/mpeg", chunks())

    async def go():
        sent: list[bytes] = []

        async def send(m):
            pass

        async def send_bytes(b):
            sent.append(b)

        sp = voice_session.Speaker(SlowTTS(), send, send_bytes)
        sp.speak("Six kilos de tomme.")
        sp.speak("Livrés demain.")
        await sp.finish()
        return sent

    sent = asyncio.run(go())
    assert [b.decode().split("|")[0] for b in sent] == ["Six kilos de tomme."] * 3 + ["Livrés demain."] * 3  # order kept
    assert starts["Livrés demain."] - starts["Six kilos de tomme."] < 0.1  # started during sentence 1 (0.15 s)


# ── never « c'est validé » before the ERP said so ──


def test_success_claim_waits_for_the_write_and_is_dropped_if_it_fails():
    g = CustomerGate()
    assert g.push("Ce oui valait pour la tomme, je confirme. ") == ""
    assert g.tool_call("confirm_order") == ""
    g.write_failed()
    assert g.finish() == "" and "je confirme" in g.internal[0]


def test_success_claim_is_said_after_an_ok_write():
    g = CustomerGate()
    g.push("Parfait, c'est validé, livraison demain. ")
    g.tool_call("confirm_order")
    assert g.write_succeeded().startswith("Parfait, c'est validé")


def test_recap_streams_clause_by_clause():
    g = CustomerGate()
    assert g.push("Quatre kilos de tomme de Savoie, ") == "Quatre kilos de tomme de Savoie, "  # no wait for the end


def test_confirmation_folded_into_another_question_is_ambiguous():  # final run, v05
    h = [u("8 kg de tomme"), a(RECAP, [DRAFT]), tool("d1", DRAFT.name, {"id": "ord_1"}), u("et de la raclette ?"),
         a("Oui, à seize euros quarante le kilo. Il vous en faut combien, et je valide la tomme en même temps ?"), u("Oui.")]  # fmt: skip
    assert not may_confirm(h, "voice")
