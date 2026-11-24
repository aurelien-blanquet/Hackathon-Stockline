"""Spoken recaps stay short (mar 03:27, s01: an 8-line « comme d'habitude » read aloud = 806 characters)."""

from app.tools.orders import say_order


def order(n):
    names = ["Reblochon de Savoie AOP fermier (450 g)", "Diots de Savoie (barquette 1 kg)", "Tomme de Savoie IGP",
             "Raclette de Savoie IGP (demi-meule)", "Jambon de Savoie IGP tranché"]
    return {"lines": [{"qty": 2 + i, "unit": "kg", "productName": names[i]} for i in range(n)],
            "deliveryDate": "2026-11-25", "totalHt": 312.5}


def test_up_to_three_lines_are_read():
    said = say_order(order(3), "2026-11-24")
    assert "Diots de Savoie" in said and "livraison demain" in said


def test_more_than_three_lines_say_the_count_and_total():
    said = say_order(order(5), "2026-11-24")
    assert said.startswith("cinq produits, livraison demain, total") and "Diots" not in said
    assert "Diots de Savoie" in say_order(order(5), "2026-11-24", compact=False)
