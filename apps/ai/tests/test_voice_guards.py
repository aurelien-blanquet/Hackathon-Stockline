"""Guards added after the 03:43 real-key run (DECISIONS §5): English thinking aloud, the internal name « marché
express », a seasonal client's closure, the near-limit encours said once."""

import json

import pytest

from app.schemas import ChatMessage
from app.services.voice_session import credit_warning, customer_words, english_aside, speaks_english
from app.tools.voice import closed_now


@pytest.mark.parametrize("sentence,aside", [
    ("Tomorrow is Wednesday, a delivery day.", True),
    ("Usual basket is large; I'll draft it now.", True),
    ("Bien sûr : comme d'habitude, huit produits pour demain, total trois mille euros.", False),
    ("Il y a deux kilos de tomme à vingt euros.", False),
    ("Je valide ?", False),
])
def test_english_aside(sentence, aside):
    assert english_aside(sentence) is aside


def test_an_english_caller_is_answered_in_english():
    assert speaks_english("Hi, this is the Brasserie Breton, I need twenty kilos of tomme for Saturday")
    assert not speaks_english("Bonjour, c'est Jean-Marc du Panier Savoyard, tu me mets comme d'habitude ?")


def test_marche_express_is_never_said():
    assert customer_words("Le marché express a déjà été lancé.") == "La demande aux producteurs a déjà été lancé."
    assert customer_words("Je valide avec le complément du marché express ?") == "Je valide avec le complément des producteurs ?"
    assert "marché express" not in customer_words("ce que le marché express peut couvrir").lower()


def test_closed_now():
    about = "Restaurant au pied des pistes. Ouvert de mi-décembre à mi-avril et en juillet-août.\n\nClient depuis 1996."
    assert closed_now(about, "2026-11-24") == "Fermé en ce moment (ouvert de mi-décembre à mi-avril et en juillet-août)."
    assert closed_now(about, "2026-01-10") is None and closed_now(about, "2026-08-01") is None
    assert closed_now("Bistrot ouvert toute l'année.", "2026-11-24") is None


def test_credit_warning_is_read_from_the_caller_card():
    card = {"found": True, "credit": {"outstanding": 19429, "creditLimit": 24000, "warning": "Encours au-delà de 80 %"}}
    assert credit_warning([ChatMessage(role="tool", name="identify_caller", content=json.dumps(card))])
    assert not credit_warning([ChatMessage(role="tool", name="identify_caller", content=json.dumps({"credit": {}}))])
