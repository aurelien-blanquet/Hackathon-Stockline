"""services/model_router.py: the fast model when the code did the work, the strong one when judgement is needed."""

import json

import pytest

from app.schemas import ChatMessage
from app.services.model_router import route


class Client:
    def __init__(self, model):
        self.model, self.provider = model, "anthropic"


STRONG, FAST = Client("claude-sonnet-5-5"), Client("claude-haiku-5-5")
IDENTIFIED = [ChatMessage(role="tool", name="identify_caller", content=json.dumps({"found": True}))]


@pytest.mark.parametrize("heard,history,preloaded,optimistic,blocked,expected", [
    ("Salut, c'est Jean-Marc, vingt kilos de tomme pour samedi", [], True, False, False, "haiku"),  # all preloaded
    ("Oui c'est bon, vas-y.", IDENTIFIED, False, True, False, "haiku"),  # plain yes: write + confirm
    ("Et si j'en prends dix ?", IDENTIFIED, False, False, False, "haiku"),  # short follow-up
    ("Le reblochon d'hier était pas bon, j'en ai jeté la moitié", IDENTIFIED, True, False, False, "sonnet"),
    ("Je veux un avoir, c'est pas la première fois.", IDENTIFIED, False, False, False, "sonnet"),
    ("Oui mais mets-en vingt-cinq plutôt.", IDENTIFIED, False, False, False, "sonnet"),  # correction
    ("Non attends, plutôt cinquante. Euh non, quinze.", IDENTIFIED, False, False, False, "sonnet"),
    ("Allô, c'est La Grolle des Gets, ma commande pour demain", [], True, False, True, "sonnet"),  # blocked
    ("Bonjour, j'ouvre un restaurant à côté, vous livrez quels jours et vous avez quoi ?", [], False, False, False, "sonnet"),
])
def test_route(heard, history, preloaded, optimistic, blocked, expected):
    llm, why = route(STRONG, heard, history, preloaded, optimistic, blocked, fast=FAST)
    assert expected in llm.model, why


def test_without_a_fast_model_every_turn_uses_llm_model():
    llm, why = route(STRONG, "Oui c'est bon", IDENTIFIED, False, True, False)  # VOICE_FAST_MODEL empty in tests
    assert llm is STRONG and why == "one model"
