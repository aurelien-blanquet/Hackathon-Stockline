"""Concise voice + integrated market: quantities heard, customer-facing offer card, no fillers by default."""

from app.services import voice_session
from app.services.fast_path import quantities_said
from app.services.offer import OfferBoard


def test_quantities_are_read_per_product():
    from test_fast_path import INDEX

    said = dict(quantities_said("vingt et un reblochons laitiers et 2,5 kilos de tomme", INDEX))
    assert said == {"reblochon laitier": 21, "tomme": 2.5}
    assert dict(quantities_said("du reblochon et du beaufort", INDEX)) == {"reblochon": None, "beaufort": None} or all(
        q is None for _, q in quantities_said("du reblochon et du beaufort", INDEX)
    )


FOUND = {"found": True, "product": {"id": "prd_0001", "name": "Reblochon de Savoie AOP fermier (450 g)", "unit": "piece", "say": "Reblochon fermier"},
         "stock": {"available": 851, "enough": False}, "price": {"unitPrice": 6.9, "say": "six euros quatre-vingt-dix"}}  # fmt: skip
SOURCED = {"sourcingId": "abc", "available": 851, "shortfall": 1149, "covered": 1149, "uncovered": 0, "inTime": True,
           "offers": [{"supplier": "GAEC des Chalets du Chinaillon", "qty": 1149, "unitPrice": 4.1, "openingPrice": 4.3, "arrives": "2026-11-25"}],
           "negotiated": {"saved": 230.0, "suppliersCalled": 4}}  # fmt: skip


def test_offer_card_is_customer_facing():
    board = OfferBoard(today="2026-11-24", delivery="2026-11-25")
    assert board.add("find_product", {"query": "reblochon fermier", "qty": 2000}, FOUND)
    assert board.add("source_product", {"productId": "prd_0001", "qty": 2000}, SOURCED)
    [line] = board.snapshot()
    assert (line.product, line.qty, line.unit_price, line.total) == ("Reblochon fermier", 2000, 6.9, 13800.0)
    assert "851" in line.availability and "demain" in line.availability
    assert line.delivery.startswith("demain")
    wire = line.to_json() if hasattr(line, "to_json") else line.model_dump_json()
    for secret in ("GAEC", "4.1", "openingPrice", "saved", "prd_0001", "abc"):  # supplier, cost, margin, ids
        assert secret not in wire


def test_ambiguous_product_asks_which_variant_without_price():
    board = OfferBoard()
    board.add("find_product", {"query": "beaufort"}, {"found": False, "candidates": [
        {"productId": "prd_0006", "name": "Beaufort AOP"}, {"productId": "prd_0005", "name": "Beaufort AOP d'été"}]})  # fmt: skip
    [line] = board.snapshot()
    assert line.options == ["Beaufort AOP", "Beaufort AOP d'été"] and line.unit_price is None and line.qty is None


def test_no_quantity_no_total_no_delivery_promise():
    board = OfferBoard(delivery="2026-11-25")
    board.add("find_product", {"query": "tomme"}, {**FOUND, "stock": {"available": 300, "enough": True}})
    [line] = board.snapshot()
    assert line.total is None and line.delivery is None and line.availability == "En stock"


def test_waiting_phrases_are_late_and_neutral_and_model_fillers_never_voiced():
    assert voice_session.ACK_AFTER_S >= 1.0  # a fast answer never gets a waiting phrase
    for filler in ["Je regarde.", "Un instant, je vérifie.", "Je vais vérifier ça.", "Je vérifie tout de suite."]:
        assert voice_session.META_TALK.search(filler), filler
    assert not voice_session.META_TALK.search("Reblochon fermier ou laitier ?")


def test_seasonal_shortage_says_why():
    board = OfferBoard()
    board.add("find_product", {"query": "beaufort d'été", "qty": 20}, {**FOUND, "stock": {"available": 0, "enough": False}})
    board.add("source_product", {"productId": "prd_0001"}, {"found": False, "available": 0, "reason": "pas avant janvier"})
    assert board.snapshot()[0].availability == "Indisponible : pas avant janvier"
