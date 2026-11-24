"""A whole market round against a fake ERP (templates only, no pauses): concurrency, floors, honesty, purchase orders."""

import json

import httpx
import pytest

from app.market import levers
from app.market.levers import FLOOR_EXTRA

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
            # a lever that works lowers the floor, by FLOOR_EXTRA at most (market/levers.py), never more
            assert o["price"] >= round(supplier_terms(profiles[e.call], needs[o["productId"]], "t").floor * (1 - FLOOR_EXTRA), 2) - 0.005
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


# ── the market at the speed of code (decision in code, orders in parallel, narration never decides) ──


def outcome(r):
    d = of(r, "decision")[0].data
    return sorted((a["supplierId"], a["productId"], a["qty"], a["price"]) for a in d["allocations"]), d["total"], d["savings"]


async def test_commercial_result_does_not_depend_on_the_display_speed(erp, monkeypatch):
    """Same data, same seed: fast mode and demo mode decide exactly the same (the narration only tells the script)."""
    monkeypatch.setattr(market_round.MarketRound, "pause", lambda self, text="", base=0.4: _no_wait())
    fast = MarketRound(erp=erp, pace=0, seed="same")
    demo = MarketRound(erp=erp, pace=1, seed="same")  # pace 1, but pauses stubbed so the test stays fast
    await fast.run()
    learned = levers.MEMORY
    levers.MEMORY = levers.LeverMemory()  # the same buyer knowledge for both (a round learns: market/levers.py)
    await demo.run()
    levers.MEMORY = learned
    assert outcome(fast) == outcome(demo)


async def _no_wait():
    return None


async def test_decision_is_taken_before_any_line_and_orders_before_the_dialogues_end(erp):
    r = await run(erp)
    m = of(r, "summary")[0].data["metrics"]
    assert m["timeToDecisionMs"] <= m["timeToOrdersCreatedMs"] <= m["timeToAllDialoguesFinishedMs"]
    assert m["exchanges"] >= 3 and m["voices"]["templates"] >= 3  # greetings / thanks without a model call


async def test_a_purchase_order_is_announced_only_once_written_and_failures_are_said(erp):
    erp_ok = erp

    class Failing(ErpClient):
        async def post(self, path, body=None):
            if path == "/api/purchase-orders" and body["supplierId"] == "sup_a":
                raise RuntimeError("ERP indisponible")
            return await erp_ok.post(path, body)

        async def get(self, path, query=None):
            return await erp_ok.get(path, query)

    failing = Failing("voice_agent", "Agent achats", base_url="http://erp", http=erp_ok.http)
    r = MarketRound(erp=failing, pace=0, seed="t")
    await r.run()
    winners = {a["supplierId"] for a in of(r, "decision")[0].data["allocations"]}
    assert "sup_a" in winners
    assert "sup_a" not in {e.call for e in of(r, "po_created")}  # never announced
    assert any(e.call == "sup_a" for e in of(r, "error"))
    assert "non passé chez Coopérative Fruitière" in of(r, "summary")[0].data["text"]
    said_to_a = " ".join(e.data["text"] for e in of(r, "line") if e.call == "sup_a")
    assert "vient de partir" not in said_to_a and "par écrit" in said_to_a
    # every announced order was really written, once
    assert len(erp_ok.posted) == len(of(r, "po_created")) == len(winners) - 1


async def test_the_buyer_never_names_a_rival(erp):
    r = await run(erp)
    names = [v[0] for v in SUPPLIERS.values()]
    for e in of(r, "line"):
        if e.data["speaker"] == "buyer":
            assert not any(n in e.data["text"] for n in names), e.data["text"]


# ── the daily « Marché du matin »: every product back to at least an average of its sales ──

REPLENISH = {"today": "2026-11-24", "days": 28, "coverDays": 7, "checked": 3, "below": 3, "lines": [
    {**NEEDS["lines"][0], "need": 30, "avgPerDay": 4.3, "target": 30, "available": 0, "incoming": 0},
    {**NEEDS["lines"][1], "need": 40, "avgPerDay": 5.7, "target": 40, "available": 0, "incoming": 0},
    {"productId": "prd_m", "name": "Mont d'Or AOP (boîte 500 g)", "unit": "piece", "category": "fromages", "cost": 9.0, "need": 12,
     "suppliers": [{"supplierId": "sup_c", "name": "GAEC", "price": 9.5}]},
]}  # fmt: skip
OUT_OF_SEASON = {"entries": [{"title": "Rupture saisonnière", "body": "À zéro depuis le 15 mai : ne sort pas avant le 10 septembre (saison). Substitut : Vacherin."}]}  # fmt: skip


@pytest.fixture
def daily_erp():
    """The round fixture's ERP, plus the replenishment need, the PO list (drafts) and cancel."""
    pos, cancelled = [], []

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/api/purchase-orders/replenishment":
            return httpx.Response(200, json=REPLENISH)
        if p == "/api/purchase-orders" and req.method == "GET":
            return httpx.Response(200, json=[po for po in pos if po["id"] not in cancelled])
        if p == "/api/purchase-orders" and req.method == "POST":
            body = json.loads(req.content)
            po = {"id": f"po_{len(pos) + 1}", "number": f"ACH-{len(pos) + 1}", "status": "draft", **body}
            pos.append(po)
            return httpx.Response(201, json={**po, "totalHt": sum(l["qty"] * l["unitPrice"] for l in body["lines"])})
        if p.endswith("/cancel"):
            cancelled.append(p.split("/")[-2])
            return httpx.Response(200, json={})
        if p == "/api/context/for" and req.url.params["entityType"] == "product":
            return httpx.Response(200, json=OUT_OF_SEASON if req.url.params["id"] == "prd_m" else {"entries": []})
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
    client.pos, client.cancelled = pos, cancelled  # type: ignore[attr-defined]
    return client


async def test_the_morning_market_replenishes_every_product_below_its_average(daily_erp):
    r = MarketRound(erp=daily_erp, pace=0, seed="t", mode="daily", trigger="automatique, chaque matin à 06:00")
    await r.run()
    assert not of(r, "error"), [e.data for e in of(r, "error")]
    started = of(r, "round_started")[0].data
    assert started["title"] == "Réassort du matin" and "automatique" in started["reference"]
    assert started["needBy"] == "2026-11-26"  # business date + REPLENISH_LEAD_DAYS, not Christmas
    assert {n["productId"] for n in started["needs"]} == {"prd_r", "prd_f"}
    # out of season (its sheet says so): said on the page, not bought
    assert [p["productId"] for p in started["skippedProducts"]] == ["prd_m"]
    assert all("prd_m" not in [l["productId"] for l in po["lines"]] for po in daily_erp.pos)
    buyer = [e.data["text"] for e in of(r, "line") if e.data.get("speaker") == "buyer"]
    assert any("Pour notre réassort" in t for t in buyer) and not any("Noël" in t for t in buyer)
    assert daily_erp.pos and all(po["note"].startswith(f"Marché du matin, réassort du {r.run_day}") for po in daily_erp.pos)
    assert "Chaque produit tient sa semaine de ventes" in of(r, "summary")[0].data["text"]


async def test_a_second_run_replaces_the_unsent_replenishment_drafts_not_the_christmas_ones(daily_erp):
    daily_erp.pos.append({"id": "po_xmas", "number": "ACH-X", "status": "draft", "note": "Marché du matin, semaine de Noël : prix négociés", "lines": []})  # fmt: skip
    await MarketRound(erp=daily_erp, pace=0, seed="t", mode="daily").run()
    first = [po["id"] for po in daily_erp.pos if po["id"] != "po_xmas"]
    await MarketRound(erp=daily_erp, pace=0, seed="t", mode="daily").run()
    assert set(daily_erp.cancelled) == set(first)  # yesterday's drafts out, the Christmas draft kept


async def test_the_schedule_buys_once_per_morning(daily_erp, monkeypatch):
    from app.market import schedule

    monkeypatch.setitem(schedule.STATE, "lastRun", None)
    assert not await schedule.done_today(daily_erp)
    await MarketRound(erp=daily_erp, pace=0, seed="t", mode="daily").run()
    assert await schedule.done_today(daily_erp)  # a restart reads it from the ERP: no second buy today


async def test_nothing_to_buy_when_every_product_holds_its_average(daily_erp, monkeypatch):
    monkeypatch.setitem(REPLENISH, "lines", [])
    r = MarketRound(erp=daily_erp, pace=0, seed="t", mode="daily")
    await r.run()
    assert not of(r, "error") and not daily_erp.pos
    assert "Rien à acheter ce matin" in of(r, "summary")[0].data["text"]


async def test_the_morning_market_buys_the_economic_lot_not_just_one_week(daily_erp):
    """Raclette (60-day shelf life, a producer who gives volume discounts): more than a week, the volume tier asked;
    the one-week floor is what a shortage is measured against."""
    r = MarketRound(erp=daily_erp, pace=0, seed="t", mode="daily")
    await r.run()
    needs = {n["productId"]: n for n in of(r, "round_started")[0].data["needs"]}
    raclette = needs["prd_r"]
    assert raclette["coverDays"] > 7 and raclette["need"] > raclette["weekNeed"] and raclette["discountPct"] > 0
    assert raclette["lotSaved"] > 0
    bought = sum(l["qty"] for po in daily_erp.pos for l in po["lines"] if l["productId"] == "prd_r")
    assert bought > raclette["weekNeed"]
    summary = of(r, "summary")[0].data
    assert summary["lotSaved"] > 0 and "lots économiques" in summary["text"]


async def test_the_morning_market_only_recommends_the_owner_approves(daily_erp):
    """Drafts only, never sent by the agent; the producer is told the owner signs first; the summary says so."""
    r = MarketRound(erp=daily_erp, pace=0, seed="t", mode="daily")
    await r.run()
    assert daily_erp.pos and all(po["status"] == "draft" for po in daily_erp.pos)
    assert all(e.data.get("pending") for e in of(r, "po_created"))
    buyer = [e.data["text"] for e in of(r, "line") if e.data.get("speaker") == "buyer"]
    assert not any("vient de partir" in t for t in buyer) and any("Le patron valide" in t for t in buyer)
    assert "rien ne part chez les producteurs avant votre validation" in of(r, "summary")[0].data["text"]


async def test_opening_the_page_starts_todays_recommendation_once(daily_erp, monkeypatch):
    from app.market import round as market_round
    from app.market import schedule

    started = []

    def fake_run_now(trigger="manuel", pace=None):
        r = MarketRound(erp=daily_erp, pace=0, seed="t", mode="daily", trigger=trigger)
        started.append(r)
        return r

    monkeypatch.setattr(schedule, "run_now", fake_run_now)
    monkeypatch.setattr(schedule, "ErpClient", lambda *a, **k: daily_erp)
    monkeypatch.setitem(schedule.STATE, "lastRun", None)
    monkeypatch.setattr(market_round, "ROUNDS", {})
    first = await schedule.ensure_today()
    assert first["started"] and started[0].trigger == "à l'ouverture de la page"
    await started[0].run()  # it wrote today's drafts
    again = await schedule.ensure_today()
    assert not again["started"] and len(started) == 1
