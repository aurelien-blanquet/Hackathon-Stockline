"""« Marché express »: the central buying agent during a customer call (app/market/express.py), against a fake ERP."""

import asyncio
import json

import httpx
import pytest

from app.market import express, voices
from app.market import round as market_round
from app.market.round import ROUNDS
from app.market.strategy import NeedLine, supplier_terms
from app.tools import TOOLS, ErpClient, ToolContext

SUPPLIERS = {  # name, contact, minimum order, stars, negotiation, lead time (days)
    "sup_a": ("Coopérative Fruitière", "Gilbert Missillier", 100, "★★★ — souplesse ★★☆", "- Remise au volume.", 1),
    "sup_b": ("Alpes Crèmerie Distribution", "David Rey", 100, "★★☆ — souplesse ★★★", "- Prix à la palette.", 1),
    "sup_c": ("GAEC des Chalets", "Henri Perrissin", 50, "★★☆ — souplesse ★☆☆", "- Prix fixe à l'année, aucune remise.", 4),
}
SOURCES = {"productId": "prd_b", "name": "Beaufort d'été AOP (meule)", "unit": "kg", "category": "fromages", "cost": 24.0,
           "price": 31.0, "available": 5, "incoming": 0,
           "suppliers": [{"supplierId": "sup_a", "name": "Coopérative Fruitière", "price": 25.2},
                         {"supplierId": "sup_b", "name": "Alpes Crèmerie Distribution"},
                         {"supplierId": "sup_c", "name": "GAEC des Chalets", "price": 24.8}]}  # fmt: skip


PRODUCT_CONTEXT = {"prd_season": [{"title": "Rupture en cours", "body": "À zéro depuis 4 jours : fin des meules de beaufort d'été 2025 à la fruitière, le millésime 2026 ne sort pas avant janvier. Substitut possible (avec accord) : Beaufort AOP (affiné 8 mois)."}]}


@pytest.fixture
def erp():
    posted, calls = [], []

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        calls.append(p)
        if p == "/api/purchase-orders/sources":
            return httpx.Response(200, json=SOURCES)
        if p == "/api/purchase-orders" and req.method == "POST":
            body = json.loads(req.content)
            posted.append(body)
            return httpx.Response(201, json={"id": f"po_{len(posted)}", "number": f"ACH-{len(posted)}", "totalHt": sum(l["qty"] * l["unitPrice"] for l in body["lines"])})  # fmt: skip
        if p.startswith("/api/suppliers/"):
            sid = p.rsplit("/", 1)[1]
            name, contact, minimum, _, _, lead = SUPPLIERS[sid]
            return httpx.Response(200, json={"id": sid, "name": name, "contacts": [{"name": contact}], "leadTimeDays": lead, "minOrderAmount": minimum, "eventStats": {"issues12m": 1}})  # fmt: skip
        if p == "/api/context/for" and req.url.params["entityType"] == "product":
            return httpx.Response(200, json={"entries": PRODUCT_CONTEXT.get(req.url.params["id"], [])})
        if p == "/api/context/for":
            _, _, _, stars, nego, _ = SUPPLIERS[req.url.params["id"]]
            return httpx.Response(200, json={"entries": [{"title": "Profil", "body": f"- **Fiabilité** : {stars}"}, {"title": "Négociation", "body": nego}]})  # fmt: skip
        return httpx.Response(404, json={"error": {"message": p}})

    client = ErpClient("voice_agent", "Agent vocal", base_url="http://erp", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client.posted, client.calls = posted, calls  # type: ignore[attr-defined]
    return client


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    class Mock:
        provider = "mock"

    async def meta():
        return {"today": "2026-11-24"}

    monkeypatch.setattr(voices, "_llm", Mock())
    monkeypatch.setattr(market_round, "get_meta", meta)
    monkeypatch.setattr(express, "get_meta", meta)
    monkeypatch.setattr(express, "_profiles", {})
    express.SOURCINGS.clear()


async def test_shortfall_is_sourced_at_once_from_suppliers_who_deliver_in_time(erp):
    r = await express.source(erp, "prd_b", 20, "cli_0001", "2026-11-26", replay=False)
    assert r["available"] == 5 and r["shortfall"] == 15 and r["inTime"] is True
    assert r["negotiated"]["suppliersCalled"] == 2  # sup_c: 4 days, too slow for Thursday
    assert {o["supplier"] for o in r["offers"]} <= {"Coopérative Fruitière", "Alpes Crèmerie Distribution"}
    assert abs(r["covered"] - 15) < 0.05 and r["uncovered"] < 0.05
    assert r["say"].startswith("Il me reste cinq kilos ;") and "€" not in r["say"]
    assert erp.posted == []  # nothing ordered before the caller says yes


async def test_negotiated_prices_never_cross_a_floor_and_beat_the_opening(erp):
    r = await express.source(erp, "prd_b", 20, delivery_date="2026-11-26", replay=False)
    s = express.SOURCINGS[r["sourcingId"]]
    for o in s.script.final:
        t = supplier_terms(s.profiles[o.supplier_id], s.line, f"express|prd_b|2026-11-24")
        assert t.floor - 0.005 <= o.price <= t.opening
    assert r["negotiated"]["saved"] >= 0


async def test_nobody_in_time_still_answers_with_the_later_date(erp):
    r = await express.source(erp, "prd_b", 20, delivery_date="2026-11-24", replay=False)  # today: nobody is that fast
    assert r["inTime"] is False and r["offers"] and "au plus tôt" in r["say"]


async def test_enough_stock_means_no_market(erp):
    r = await express.source(erp, "prd_b", 4, replay=False)
    assert r["needed"] is False and "/api/suppliers/sup_a" not in erp.calls


async def test_supplier_orders_after_yes_are_placed_once(erp):
    r = await express.source(erp, "prd_b", 20, "cli_0001", "2026-11-26", replay=False)
    first = await express.place_orders(erp, r["sourcingId"])
    again = await express.place_orders(erp, r["sourcingId"])
    assert len(erp.posted) == len(first["orders"]) >= 1 and again["alreadyPlaced"]
    assert all(b["note"].startswith("Marché express") and b["expectedDate"] == "2026-11-25" for b in erp.posted)


async def test_the_page_replays_exactly_what_the_caller_was_told(erp):
    r = await express.source(erp, "prd_b", 20, "cli_0001", "2026-11-26")
    rnd = ROUNDS[r["roundId"]]
    rnd.pace = 0
    for _ in range(200):
        if rnd.done:
            break
        await asyncio.sleep(0.01)
    types = [e.type for e in rnd.events]
    assert types[0] == "round_started" and "decision" in types and types[-1] == "summary"
    decision = next(e for e in rnd.events if e.type == "decision").data
    told = {(o["supplier"], o["qty"], o["unitPrice"]) for o in r["offers"]}
    names = {sid: p.name for sid, p in express.SOURCINGS[r["sourcingId"]].profiles.items()}
    assert {(names[a["supplierId"]], a["qty"], a["price"]) for a in decision["allocations"]} == told
    assert sum(1 for e in rnd.events if e.type == "call_ended") == 2


async def test_tools_are_registered_for_the_voice_agent(erp):
    ctx = ToolContext(erp=erp, actor="voice_agent")
    r = await TOOLS["source_product"].run({"productId": "prd_b", "qty": 20, "deliveryDate": "2026-11-26"}, ctx)
    out = await TOOLS["create_supplier_orders"].run({"sourcingId": r["sourcingId"]}, ctx)
    assert out["orders"] and out["say"].startswith("C'est commandé chez")


def test_negotiation_is_deterministic():
    profiles = {}
    line = NeedLine("prd_x", "Tomme", "kg", "fromages", 10.0, 30, {"a": 10.5})
    from app.market.strategy import SupplierProfile

    profiles = {"a": SupplierProfile("a", "A", flexibility=3), "b": SupplierProfile("b", "B", flexibility=2)}
    one, two = express.negotiate([line], profiles, "s"), express.negotiate([line], profiles, "s")
    assert [(o.supplier_id, o.price) for o in one.final] == [(o.supplier_id, o.price) for o in two.final]


async def test_a_seasonal_rupture_calls_nobody_and_says_why(erp):
    """Data: « le millésime 2026 ne sort pas avant janvier » — no producer has any: the agent must not promise one."""
    r = await express.source(erp, "prd_season", 12, "cli_0001", "2026-11-26", replay=False)
    assert r["found"] is False and "/api/suppliers/sup_a" not in erp.calls
    assert r["say"] == "Aucun producteur ne peut en fournir en ce moment : fin des meules de beaufort d'été 2025 à la fruitière, le millésime 2026 ne sort pas avant janvier."
    assert r["substitute"] == "Beaufort AOP (affiné 8 mois)"


def test_a_plain_rupture_still_goes_to_market():
    ctx = {"entries": [{"title": "Rupture en cours", "body": "À zéro depuis 2 jours : livraison du fournisseur en retard."}]}
    assert express.supply_blocked(ctx) is None


async def test_the_client_order_places_the_producers_orders(erp):
    # mar 03:43, s14: the model wrote the client order after « réserve-moi tout » and forgot create_supplier_orders
    await express.source(erp, "prd_b", 20, "cli_0001", "2026-11-26", replay=False)
    order = {"status": "draft", "clientId": "cli_0001", "lines": [{"productId": "prd_b", "qty": 20}]}
    placed = await express.place_for_order(erp, order)
    assert placed and len(erp.posted) == len(placed)
    assert await express.place_for_order(erp, order) == [] and len(erp.posted) == len(placed)  # once


async def test_an_order_within_our_stock_places_nothing(erp):
    await express.source(erp, "prd_b", 20, "cli_0001", "2026-11-26", replay=False)
    # the caller said « non, juste ce que vous avez » : five kilos, our own stock
    assert await express.place_for_order(erp, {"status": "draft", "clientId": "cli_0001", "lines": [{"productId": "prd_b", "qty": 5}]}) == []
    assert erp.posted == []
