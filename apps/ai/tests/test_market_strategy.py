"""The market's numbers are code: floors are never crossed, the decision is explainable and honest about shortages."""

from app.market.strategy import (
    NeedLine,
    Offer,
    SupplierProfile,
    allocate,
    counter,
    effective_price,
    parse_stars,
    supplier_terms,
)

COOP = SupplierProfile("sup_0001", "Coopérative", lead_time_days=1, min_order=500, reliability=3, flexibility=2)
ALPES = SupplierProfile("sup_0006", "Alpes Crèmerie", lead_time_days=1, min_order=600, reliability=2, flexibility=3, issues_12m=13)
RACLETTE = NeedLine("prd_0013", "Raclette meule", "kg", "raclette", cost=12.0, need=9000, list_prices={"sup_0001": 12.6})


def test_stars_from_the_supplier_sheet():
    assert parse_stars("- **Fiabilité** : ★★☆ — souplesse ★★★ — négociateur, pressé") == (2, 3)
    assert parse_stars("rien") == (2, 2)


def test_terms_regular_supplier_vs_occasional_one():
    coop, alpes = supplier_terms(COOP, RACLETTE, "s"), supplier_terms(ALPES, RACLETTE, "s")
    assert coop.regular and not alpes.regular
    assert coop.floor < 12.6 < coop.opening  # asks above its list, can go a bit below
    assert alpes.floor > RACLETTE.cost  # not their usual product: dearer than our cost
    assert coop.capacity >= 0.65 * 9000 and alpes.capacity <= 0.55 * 9000  # nobody covers Christmas alone
    assert supplier_terms(COOP, RACLETTE, "s") == coop  # same seed, same market


def test_counter_matches_competition_but_never_crosses_the_floor():
    t = supplier_terms(COOP, RACLETTE, "s")
    price, final = counter(t, t.opening, competitor=t.opening - 0.2)
    assert price == round(t.opening - 0.21, 2) and not final
    price, final = counter(t, t.opening, competitor=1.0)  # absurd competitor price
    assert price == t.floor and final
    price, _ = counter(t, t.opening, competitor=None)  # no competition: a small volume gesture
    assert t.floor <= price < t.opening


def test_unreliable_supplier_pays_a_penalty():
    o = Offer("x", "p", 10.0, 1)
    assert effective_price(o, COOP) == 10.0
    assert effective_price(o, ALPES) > 10.2  # one star missing + 13 incidents


def test_allocate_cheapest_reliable_cover_within_capacity():
    offers = [Offer("sup_0001", "prd_0013", 12.3, 6000), Offer("sup_0006", "prd_0013", 12.2, 4000)]
    d = allocate([RACLETTE], offers, {"sup_0001": COOP, "sup_0006": ALPES})
    # Alpes is 0.10 cheaper but its reliability penalty makes the coop first; Alpes takes the rest
    assert [(a.supplier_id, a.qty) for a in d.allocations] == [("sup_0001", 6000), ("sup_0006", 3000)]
    assert d.uncovered == {} and d.total == round(6000 * 12.3 + 3000 * 12.2, 2)
    assert d.savings == 0  # no opening given: nothing negotiated


def test_shortage_is_reported_not_hidden():
    d = allocate([RACLETTE], [Offer("sup_0001", "prd_0013", 12.3, 5000)], {"sup_0001": COOP})
    assert d.uncovered == {"prd_0013": 4000}


def test_supplier_under_its_minimum_is_dropped_when_others_can_cover():
    small = NeedLine("prd_x", "Œufs", "box", "cremerie", cost=6.8, need=10, list_prices={"sup_0001": 7.0})
    offers = [Offer("sup_0006", "prd_x", 6.5, 10), Offer("sup_0001", "prd_x", 7.0, 10)]
    d = allocate([small], offers, {"sup_0001": COOP, "sup_0006": ALPES})
    assert d.dropped_min_order == ["sup_0006"] and d.allocations[0].supplier_id == "sup_0001"


def test_savings_are_what_the_negotiation_saved_and_coverage_is_reported():
    offers = [Offer("sup_0001", "prd_0013", 12.0, 6000, opening=12.8), Offer("sup_0006", "prd_0013", 13.0, 2000, opening=13.4)]
    d = allocate([RACLETTE], offers, {"sup_0001": COOP, "sup_0006": ALPES})
    assert d.savings == round(6000 * 0.8 + 2000 * 0.4, 2)
    assert (d.needed, d.covered) == (9000, 8000) and d.uncovered == {"prd_0013": 1000}


def test_fixed_price_supplier_never_moves():
    from app.market.strategy import is_fixed_price

    assert is_fixed_price("- Prix fixe à l'année, aucune remise.") and not is_fixed_price("- Prix à la palette.")
    gaec = SupplierProfile("sup_0002", "GAEC", flexibility=1, fixed_price=True)
    fermier = NeedLine("prd_0001", "Reblochon fermier", "piece", "fromages", cost=7.15, need=3400, list_prices={"sup_0002": 7.22})
    t = supplier_terms(gaec, fermier, "s")
    assert t.opening == t.floor == 7.22
    assert counter(t, t.opening, competitor=7.0) == (7.22, True)


def test_minimum_orders_never_cascade_into_buying_nothing():
    """Small urgent quantity, every supplier under its minimum: keep them rather than drop everyone."""
    from app.market.strategy import NeedLine, Offer, SupplierProfile, allocate

    line = NeedLine("p", "Beaufort", "kg", "fromages", 25.0, 12, {"a": 26.0, "b": 25.5})
    sup = {"a": SupplierProfile("a", "A", min_order=500), "b": SupplierProfile("b", "B", min_order=600)}
    offers = [Offer("a", "p", 26.0, 6), Offer("b", "p", 25.5, 8)]
    d = allocate([line], offers, sup)
    assert sum(a.qty for a in d.allocations) == 12 and not d.uncovered



# ── the economic lot (daily replenishment): one week is the reorder point, not the quantity ──


def test_a_fresh_product_is_bought_one_week_at_a_time():
    from app.market.strategy import economic_lot

    lot = economic_lot(avg=0.55, have=0.5, unit="kg", price=6.45, shelf_days=10)  # sérac: sold within 5 days
    assert lot.cover_days == 7 and lot.qty == lot.week_qty and lot.saved == 0


def test_a_long_keeping_product_is_bought_by_the_month_when_the_volume_discount_beats_the_storage():
    from app.market.strategy import economic_lot

    lot = economic_lot(avg=3.3, have=16, unit="kg", price=12.85, shelf_days=60)  # raclette au poivre
    assert lot.cover_days == 28  # half of its 60 days: never more
    assert lot.qty > 4 * lot.week_qty and lot.discount > lot.holding and lot.cost < lot.week_cost and lot.saved > 0


def test_never_longer_than_half_the_shelf_life_nor_the_cap():
    from app.market.strategy import economic_lot

    for shelf in (12, 21, 30, 45, 60, 120, 1095):
        lot = economic_lot(avg=5, have=0, unit="piece", price=10, shelf_days=shelf, max_days=42)
        assert lot.cover_days <= max(7, min(42, shelf / 2))


def test_a_fixed_price_producer_gives_no_volume_discount_so_the_lot_stays_smaller():
    from app.market.strategy import economic_lot

    with_tier = economic_lot(avg=3.3, have=16, unit="kg", price=12.85, shelf_days=60)
    fixed = economic_lot(avg=3.3, have=16, unit="kg", price=12.85, shelf_days=60, discount=False)
    assert fixed.discount == 0 and fixed.cost >= with_tier.cost and fixed.saved < with_tier.saved
