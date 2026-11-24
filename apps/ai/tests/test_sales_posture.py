"""The seller adapts to the caller: signals read in code, one ladder step per objection, no pressure after a no."""

import pytest

from app.services.sales_posture import Posture, coach, signals

ARGS = {"product": "Reblochon de Savoie AOP fermier", "unit": "piece", "facts": ["AOP : appellation contrôlée"],
        "perPortion": {"grams": 150, "price": 3.13}, "cheaper": {"name": "Reblochon de Savoie AOP laitier", "price": 7.2}}  # fmt: skip


@pytest.mark.parametrize(("said", "expected"), [
    ("Ah, c'est cher quand même.", "price"),
    ("Chez Metro on me le fait moins cher.", "competitor"),
    ("Bof, je sais pas trop.", "hesitant"),
    ("Je vais réfléchir, je vous rappelle.", "leaving"),
    ("Il est bon en ce moment, le beaufort ?", "quality"),
    ("Parfait, va pour ça.", "convinced"),
    ("Non merci, ça ira.", "refusal"),
])  # fmt: skip
def test_signals(said, expected):
    assert expected in signals(said)


def test_yes_but_expensive_is_an_objection_not_a_yes():
    assert signals("D'accord mais c'est cher.") == ["price"]


def test_price_ladder_one_step_per_objection():
    st = Posture()
    stances = [coach(st, ["price"], ARGS)["stance"] for _ in range(5)]
    assert stances == ["justify_value", "reframe", "honest_alternative", "trade_off_offer", "manager"]


def test_ladder_skips_steps_without_data_and_offers_one_discount():
    st = Posture()
    first = coach(st, ["price"], {"facts": [], "perPortion": None, "cheaper": None})
    assert first["stance"] == "trade_off_offer"  # nothing to argue with: straight to the bounded offer
    assert coach(st, ["price"], {})["stance"] == "manager"  # never a second discount


def test_no_twice_is_respected_and_convinced_closes():
    st = Posture()
    coach(st, ["refusal"], None)
    assert coach(st, ["refusal"], None)["stance"] == "respect"
    assert coach(Posture(), ["convinced"], None) is None  # a yes is read by the model in context, never forced to close


def test_leaving_gets_no_discount():
    c = coach(Posture(), ["leaving"], ARGS)
    assert c["stance"] == "keep_door_open" and "Pas de remise" in c["do"]


def test_neutral_sentence_changes_nothing():
    assert coach(Posture(), signals("Il me faut vingt reblochons pour samedi."), ARGS) is None


def test_best_price_question_opens_options_not_a_refusal():
    sig = signals("Euh, j'aimerais bien le laitier à 7 euros 20. Est-ce que c'est le meilleur prix que vous proposez ?")
    assert "best_price" in sig and "hesitant" not in sig
    c = coach(Posture(), sig, ARGS)
    assert c["stance"] == "show_best_options" and "propose_deal" in c["do"] and "Jamais « pas de remise »" in c["do"]


# ── who is calling, and in what state: before any selling ──

@pytest.mark.parametrize(("said", "stance"), [
    ("T'es vraiment une idiote, tu comprends rien.", "calm_boundary"),
    ("Bonjour, c'est bien la pizzeria ? Je voudrais deux margheritas.", "wrong_number"),
    ("Il me faut un million de reblochons pour mon chat, livrés sur la lune.", "prank"),
    ("Attendez, vous êtes un robot ?", "honest_ai"),
    ("Je veux parler à quelqu'un, passez-moi un commercial.", "human_callback"),
    ("C'est inadmissible, la tomme d'hier était moisie !", "empathy_first"),
    ("C'est urgent, j'ai plus rien en rayon pour ce soir.", "urgent"),
    ("Pardon ? J'ai pas compris.", "rephrase"),
    ("Ça va vous ? Il fait beau chez vous ?", "warm"),
])  # fmt: skip
def test_situations(said, stance):
    assert coach(Posture(), signals(said), ARGS)["stance"] == stance


def test_second_insult_ends_politely_and_swearing_is_not_an_insult():
    st = Posture()
    coach(st, signals("Espèce d'abruti."), None)
    assert coach(st, signals("Connard."), None)["stance"] == "polite_end"
    assert "insult" not in signals("Putain, c'est cher quand même.")


def test_situation_beats_selling():
    assert coach(Posture(), signals("C'est scandaleux, et en plus c'est trop cher."), ARGS)["stance"] == "empathy_first"


def test_a_budget_is_not_a_price_objection():
    assert "price" not in signals("J'ai un budget de quatre cents euros pour du reblochon et de l'emmental.")
    assert "price" in signals("Ça dépasse mon budget, c'est trop cher.")
