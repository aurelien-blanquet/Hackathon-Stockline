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
    assert coach(Posture(), ["convinced"], None)["stance"] == "close"


def test_leaving_gets_no_discount():
    c = coach(Posture(), ["leaving"], ARGS)
    assert c["stance"] == "keep_door_open" and "Pas de remise" in c["do"]


def test_neutral_sentence_changes_nothing():
    assert coach(Posture(), signals("Il me faut vingt reblochons pour samedi."), ARGS) is None
