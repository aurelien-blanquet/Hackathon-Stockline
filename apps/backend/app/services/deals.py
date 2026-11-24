"""
« Le comité de prix »: the arbiter of a deal desk. During a call, side agents (buyer, stock, credit, sales) gather their
facts in parallel (apps/ai/app/services/deal_desk.py); this decides, in code, which offers to make the client.

Options (each within the house rules of services/discounts.py: ≤ 5 %, never below cost + 12 %, nothing for a blocked
or late-paying client):
    A  list price, the quantity asked
    B  volume discount on the quantity asked (discounts.volume_offer)
    C  « take more »: the quantity asked + short-dated stock to clear (lots expiring within CLEAR_DAYS) or a round-up
       to the next discount step, one more point of discount (still within the caps)

Each option: margin (€), probability the client accepts (simple model: a bigger gesture is more likely accepted, a much
bigger quantity a bit less), waste avoided (cost of short-dated stock it clears), expected value = p × (margin + waste
avoided). The best is proposed first, the runner-up as the alternative. Margin and costs are for the staff screen only.
"""

from __future__ import annotations

from app import crud
from app.core.activity import today
from app.core.db import Doc
from app.core.utils import add_days, round2
from app.services import clients, discounts, pricing, stock

CLEAR_DAYS = 21  # a lot expiring within 3 weeks is offered first (cheeses: the end of its selling window)
STEP_UP = [1500.0, 3000.0, 6000.0, 10000.0]  # discounts.STEPS thresholds, for « take a bit more, get the next step »


def _accept(pct: float, qty: float, asked: float, objection: bool) -> float:
    p = (0.35 if objection else 0.55) + 0.08 * pct
    if qty > asked * 1.01:
        p -= 0.12 + 0.1 * min(1.0, (qty - asked) / asked)  # asking them to take more is a harder sell
    return round(max(0.05, min(0.95, p)), 2)


def _round_qty(q: float, unit: str) -> float:
    return float(round(q)) if unit in ("piece", "box", "dozen") else round(q * 2) / 2


def deal_options(client_id: str, product_id: str, qty: float, negotiated_cost: float | None = None,
                 objection: bool = True) -> Doc:  # fmt: skip
    client = crud.clients.require(client_id)
    product = crud.products.require(product_id)
    unit = product.get("unit") or "kg"
    r = pricing.resolve_price(client_id, product_id, qty)
    price, cost = float(r["price"]), float(r.get("cost") or product.get("cost") or 0)
    if negotiated_cost and 0 < negotiated_cost < cost:
        cost = negotiated_cost
    level = stock.stock_level(product_id)
    limit_day = add_days(today(), CLEAR_DAYS)
    expiring = round(sum(l["qtyRemaining"] for l in level.get("lots") or [] if l["expiresAt"] <= limit_day), 3)
    usual = next((u for u in clients.usual_basket(client_id) if u["productId"] == product_id), None)
    balances = clients.client_balances(client_id)

    facts = {
        "buyer": {"usualCost": float(r.get("cost") or 0), "negotiatedCost": negotiated_cost},
        "stock": {"available": level.get("available"), "expiringQty": expiring, "expiringBefore": limit_day,
                  "nextExpiry": level.get("nextExpiry")},
        "credit": {"status": client.get("status"), "outstanding": balances.get("outstanding"), "overdue": balances.get("overdue"),
                   "creditLimit": client.get("creditLimit")},
        "sales": {"usualQty": usual["avgQty"] if usual else None, "priceSource": r.get("source"),
                  "deliveryDays": client.get("deliveryDays")},
    }  # fmt: skip

    def option(key: str, q: float, pct: float, why: str, cleared: float = 0.0) -> Doc:
        unit_price = round2(price * (1 - pct / 100))
        margin = round2((unit_price - cost) * q)
        waste = round2(cleared * cost)
        p = _accept(pct, q, qty, objection)
        return {"key": key, "qty": q, "unit": unit, "pct": pct, "unitPrice": unit_price, "listUnitPrice": price,
                "total": round2(unit_price * q), "margin": margin, "wasteAvoided": waste, "pAccept": p,
                "expected": round2(p * (margin + waste)), "why": why}  # fmt: skip

    options = [option("A", qty, 0.0, "prix habituel")]
    b = discounts.volume_offer(client_id, product_id, qty, None, negotiated_cost)
    if b.get("eligible"):
        options.append(option("B", qty, b["pct"], "remise volume"))
    blocked = b.get("reason") in ("blocked", "overdue")
    if not blocked:
        # C: take more — the short-dated lots (up to +50 % of the order), else up to the next discount step
        extra = min(expiring, max(qty * 0.5, 0)) if expiring > 0 else 0.0
        why = "écouler un lot à date courte"
        if extra <= 0:
            nxt = next((s for s in STEP_UP if s > price * qty), None)
            extra = (nxt / price - qty) if nxt and nxt / price <= qty * 1.5 else 0.0
            why = "palier de remise suivant"
        q2 = _round_qty(qty + extra, unit)
        if q2 > qty:
            c = discounts.volume_offer(client_id, product_id, q2, None, negotiated_cost)
            pct2 = min(discounts.LIMIT_PCT, (c["pct"] if c.get("eligible") else 0.0) + 1.0)
            if cost > 0:
                pct2 = min(pct2, max(0.0, (1 - cost * (1 + discounts.MIN_MARGIN) / price) * 100))
            pct2 = int(pct2 * 2) / 2
            if pct2 > (options[-1]["pct"] if options else 0):
                # the asked quantity takes the oldest lots anyway (FIFO): only the EXTRA clears what would expire
                cleared = max(0.0, min(expiring, q2) - min(expiring, qty)) if why.startswith("écouler") else 0.0
                options.append(option("C", q2, pct2, why, cleared))

    ranked = sorted(options, key=lambda o: o["expected"], reverse=True)
    best = ranked[0]
    alt = next((o for o in ranked[1:] if o["key"] != "A" or best["key"] != "A"), None)
    return {"clientId": client_id, "productId": product_id, "productName": product["name"], "askedQty": qty,
            "facts": facts, "options": options, "chosen": best["key"], "alternative": alt["key"] if alt else None,
            "blocked": b.get("reason") if blocked else None, "manager": discounts.MANAGER, "maxPct": discounts.LIMIT_PCT}  # fmt: skip
