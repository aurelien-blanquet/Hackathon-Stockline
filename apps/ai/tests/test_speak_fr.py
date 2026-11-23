"""Offline tests for app.agent.speak_fr (run with `make test`)."""
import pytest

from app.agent.speak_fr import say_date, say_int, say_number, say_order_ref, say_price, say_qty


@pytest.mark.parametrize("n,expected", [
    (0, "zéro"), (1, "un"), (17, "dix-sept"), (21, "vingt et un"), (22, "vingt-deux"), (70, "soixante-dix"),
    (71, "soixante et onze"), (77, "soixante-dix-sept"), (80, "quatre-vingts"), (81, "quatre-vingt-un"),
    (91, "quatre-vingt-onze"), (99, "quatre-vingt-dix-neuf"), (100, "cent"), (101, "cent un"),
    (200, "deux cents"), (245, "deux cent quarante-cinq"), (1000, "mille"), (1250, "mille deux cent cinquante"),
    (80000, "quatre-vingt mille"), (2_000_000, "deux millions"),
])
def test_say_int(n, expected):
    assert say_int(n) == expected


def test_say_number():
    assert say_number(12.0) == "douze"
    assert say_number(1.5) == "un virgule cinq"
    assert say_number(2.25) == "deux virgule vingt-cinq"
    assert say_number(3.05) == "trois virgule zéro cinq"


def test_say_price():
    assert say_price(18.5) == "dix-huit euros cinquante"
    assert say_price(1) == "un euro"
    assert say_price(0.9) == "quatre-vingt-dix centimes"
    assert say_price(24, per="kilo") == "vingt-quatre euros le kilo"
    assert say_price(12.05) == "douze euros cinq"


def test_say_qty():
    assert say_qty(12, "kg") == "douze kilos"
    assert say_qty(1, "kg") == "un kilo"
    assert say_qty(1.5, "kg") == "un kilo et demi"
    assert say_qty(2.5, "kg") == "deux kilos et demi"
    assert say_qty(1, "meule") == "une meule"
    assert say_qty(0.5, "caisse") == "une demi-caisse"
    assert say_qty(30, "douzaine") == "trente douzaines"
    assert say_qty(3, "plateau") == "trois plateaux"


def test_say_date():
    assert say_date("2026-11-26") == "jeudi vingt-six novembre"
    assert say_date("2026-12-01") == "mardi premier décembre"
    assert say_date("2026-11-24", today="2026-11-23") == "demain"
    assert say_date("2026-11-27", today="2026-11-23") == "vendredi vingt-sept novembre"


def test_say_order_ref():
    assert say_order_ref("CMD-2026-000124") == "la commande cent vingt-quatre"
