"""A whole market round against a fake ERP (templates only, no pauses): concurrency, floors, honesty, purchase orders."""

import json

import httpx
import pytest

from app.market import round as market_round
from app.market import voices
from app.market.round import MarketRound
from app.market.strategy import SupplierProfile, supplier_terms
from app.tools import ErpClient

NEEDS = {"lines": [
    {"productId": "prd_r", "name": "Raclette de Savoie IGP au lait cru (meule 6 kg)", "unit": "kg", "category": "raclette", "cost": 12.0, "need": 9000,
     "suppliers": [{"supplierId": "sup_a", "name": "Coopérative", "price": 12.6}, {"supplierId": "sup_b", "name": "Alpes Crèmerie"}]},
    {"productId": "prd_f", "name": "Reblochon de Savoie AOP fermier (450 g)", "unit": "piece", "category": "fromages", "cost": 7.15, "need": 3400,
     "suppliers": [{"supplierId": "sup_a", "name": "Coopérative", "price": 7.71}, {"supplierId": "sup_c", "name": "GAEC", "price": 7.22}]},
]}  # fmt: skip
SUPPLIERS = {
    "sup_a": ("Coopérative Fruitière", "Gilbert Missillier", 500, "★★★ — souplesse ★★☆", "- Remise de 2 % au-delà de 2 tonnes."),
    "sup_b": ("Alpes Crèmerie Distribution", "David Rey", 600, "★★☆ — souplesse ★★★", "- Prix à la palette."),
    "sup_c": ("GAEC des Chalets", "Henri Perrissin", 150, "★★☆ — souplesse ★☆☆", "- Prix fixe à l'année, aucune remise."),
    "sup_d": ("Cellier des Abymes", "Jeanne", 400, "★★★ — souplesse ★★☆", "-"),
}


@pytest.fixture
def erp():
    posted = []

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/api/purchase-orders/needs":
            return httpx.Response(200, json=NEEDS)
        if p == "/api/purchase-orders" and req.method == "POST":
            body = json.loads(req.content)
            posted.append(body)
            return httpx.Response(201, json={"id": f"po_{len(posted)}", "number": f"ACH-{len(posted)}", "totalHt": sum(l["qty"] * l["unitPrice"] for l in body["lines"])})  # fmt: skip
        if p == "/api/suppliers":
            return httpx.Response(200, json=[{"id": sid, "name": v[0], "city": "Thônes", "categories": []} for sid, v in SUPPLIERS.items()])
        if p.startswith("/api/suppliers/"):
            sid = p.rsplit("/", 1)[1]
            name, contact, minimum, *_ = SUPPLIERS[sid]
            return httpx.Response(200, json={"id": sid, "name": name, "contacts": [{"name": contact}], "leadTimeDays": 1, "minOrderAmount": minimum, "eventStats": {"issues12m": 3}})  # fmt: skip
        if p == "/api/context/for":
            _, _, _, stars, nego = SUPPLIERS[req.url.params["id"]]
            return httpx.Response(200, json={"entries": [{"title": "Profil", "body": f"- **Fiabilité** : {stars}"}, {"title": "Négociation", "body": nego}]})  # fmt: skip
        return httpx.Response(404, json={"error": {"message": p}})

    client = ErpClient("voice_agent", "Agent achats", base_url="http://erp", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client.posted = posted  # type: ignore[attr-defined]
    return client


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    class Mock:
        provider = "mock"

    async def meta():
        return {"today": "2026-11-24"}

    monkeypatch.setattr(voices, "_llm", Mock())  # templates only: no model call in tests
    monkeypatch.setattr(market_round, "get_meta", meta)


async def run(erp) -> MarketRound:
    r = MarketRound(erp=erp, pace=0, seed="t")
    await r.run()
    assert not any(e.type == "error" for e in r.events), [e.data for e in r.events if e.type == "error"]
    return r


def of(r, type_):
    return [e for e in r.events if e.type == type_]


async def test_every_relevant_supplier_is_called_at_the_same_time(erp):
    r = await run(erp)
    called = {"sup_a", "sup_b", "sup_c"}
    assert {e.call for e in of(r, "call_connected")} == called == {e.call for e in of(r, "call_ended")}
    assert [e.call for e in of(r, "call_skipped")] == ["sup_d"]  # nothing to buy from the wine cellar this week
    # all calls are connected before the first one ends: they overlap
    assert max(e.t for e in of(r, "call_connected")) <= min(e.t for e in of(r, "call_ended"))
    assert r.done and of(r, "summary")


async def test_no_supplier_ever_sells_below_its_floor_and_fixed_price_never_moves(erp):
    r = await run(erp)
    started = of(r, "round_started")[0].data
    assert {s["id"] for s in started["suppliers"] if s["called"]} == {"sup_a", "sup_b", "sup_c"}
    profiles = {"sup_a": SupplierProfile("sup_a", "", reliability=3, flexibility=2), "sup_b": SupplierProfile("sup_b", "", reliability=2, flexibility=3),  # fmt: skip
                "sup_c": SupplierProfile("sup_c", "", reliability=2, flexibility=1, fixed_price=True)}  # fmt: skip
    needs = {l.product_id: l for l in r_needs()}
    for e in of(r, "offer"):
        for o in e.data["offers"]:
            assert o["price"] >= supplier_terms(profiles[e.call], needs[o["productId"]], "t").floor
    gaec_prices = {o["price"] for e in of(r, "offer") if e.call == "sup_c" for o in e.data["offers"]}
    assert gaec_prices == {7.22}


def r_needs():
    from app.market.strategy import NeedLine

    return [NeedLine(l["productId"], l["name"], l["unit"], l["category"], l["cost"], l["need"], {s["supplierId"]: s["price"] for s in l["suppliers"] if "price" in s}) for l in NEEDS["lines"]]  # fmt: skip


async def test_competitor_prices_the_buyer_quotes_are_real_offers(erp):
    r = await run(erp)
    offered = {(e.call, o["productId"], o["price"]) for e in of(r, "offer") for o in e.data["offers"]}
    for e in of(r, "intel"):
        assert e.data["fromCall"] != e.call and (e.data["fromCall"], e.data["productId"], e.data["price"]) in offered


async def test_purchase_orders_match_the_decision(erp):
    r = await run(erp)
    decision = of(r, "decision")[0].data
    by_supplier = {}
    for a in decision["allocations"]:
        by_supplier.setdefault(a["supplierId"], []).append((a["productId"], a["qty"], a["price"]))
    posted = {po["supplierId"]: [(l["productId"], l["qty"], l["unitPrice"]) for l in po["lines"]] for po in erp.posted}
    assert posted == by_supplier and len(of(r, "po_created")) == len(by_supplier)
    assert all(po["expectedDate"] == "2026-12-18" for po in erp.posted)
    assert decision["savings"] >= 0 and decision["covered"] <= decision["needed"]
    won = {e.call for e in of(r, "call_ended") if e.data["won"]}
    assert won == set(by_supplier)


async def test_stream_replays_then_follows_live_then_ends():
    import asyncio

    from app.routers.market import replay

    r = MarketRound(erp=None, pace=0, seed="s")  # no ERP needed: we emit by hand
    await r.emit("round_started", suppliers=[])
    seen = []

    async def watch():
        async for ev in replay(r):
            seen.append(ev.type)

    task = asyncio.create_task(watch())
    await asyncio.sleep(0.01)
    assert seen == ["round_started"]  # what happened before the page connected
    await r.emit("call_ringing", call="a")
    await asyncio.sleep(0.01)
    assert seen == ["round_started", "call_ringing"]  # then live
    async with r.updated:
        r.done = True
        r.updated.notify_all()
    await asyncio.wait_for(task, 1)  # and the stream ends with the round
