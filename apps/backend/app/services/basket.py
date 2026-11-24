"""
A basket built to a budget (« fais-moi le panier optimal pour 400 € »), decided here, never by the model.

A good shopkeeper uses the client's whole budget, keeps the basket sensible for the client's use, and, without saying
so, leans toward the lines that earn the most. So:

    shares      the budget is split between the products: equal by default, or the shares the client asked for
                (« plus de reblochon », « trop de reblochon par rapport à l'emmental » → the model passes new shares)
    tilt        each share is tilted toward the product's margin rate (MARGIN_TILT: a nudge, not a takeover)
    units       whole pieces / boxes, half-kilos; never more than the available stock
    fill        what is left of the budget goes, unit by unit, to the line with the best margin rate that still fits
                and is not already above its share (the basket stays balanced)
    result      lines (qty, client price, line total), total ≤ budget, how much of the budget is used

Client prices come from pricing.resolve_price (negotiated > rule > list). Costs and margins stay in the ERP: the
answer has a `margin` field for the staff screen only (the voice tool drops it).
"""

from __future__ import annotations

from app import crud
from app.core.db import Doc
from app.core.errors import bad_request
from app.core.utils import round2
from app.services import pricing, stock

MARGIN_TILT = 0.6  # 0 = shares as asked; 1 = shares × (1 + margin rate) fully
STEP = {"kg": 0.5, "liter": 0.5}  # other units: whole units


def _step(unit: str) -> float:
    return STEP.get(unit, 1.0)


def build_basket(client_id: str, budget: float, items: list[Doc]) -> Doc:
    if budget <= 0:
        raise bad_request("invalid_budget", "Le budget doit être positif")
    crud.clients.require(client_id)
    if not items:
        raise bad_request("no_products", "Au moins un produit")
    raw = []
    for it in items:
        p = crud.products.require(it["productId"])
        r = pricing.resolve_price(client_id, p["id"], 1)
        price, cost = float(r["price"]), float(r.get("cost") or p.get("cost") or 0)
        rate = max(0.0, (price - cost) / price) if price else 0.0
        avail = float(stock.stock_level(p["id"]).get("available") or 0)
        raw.append({"product": p, "price": price, "cost": cost, "rate": rate, "available": avail, "share": float(it.get("share") or 1.0)})
    total_share = sum(x["share"] for x in raw) or 1.0
    weights = [(x["share"] / total_share) * (1 + MARGIN_TILT * x["rate"]) for x in raw]
    wsum = sum(weights) or 1.0
    lines = []
    for x, w in zip(raw, weights, strict=True):
        step = _step(x["product"]["unit"])
        target = budget * w / wsum
        qty = max(step, int(target / x["price"] / step) * step)  # at least one unit of each product asked for
        qty = min(qty, int(x["available"] / step) * step) if x["available"] > 0 else 0.0
        lines.append({**x, "qty": qty, "target": target})

    def spent() -> float:
        return sum(line["qty"] * line["price"] for line in lines)

    # fill the rest of the budget: best margin rate first, without going far above its share (balanced basket)
    while True:
        left = budget - spent()
        candidates = [line for line in lines
                      if line["price"] * _step(line["product"]["unit"]) <= left + 1e-9
                      and line["qty"] + _step(line["product"]["unit"]) <= line["available"]
                      and (line["qty"] + _step(line["product"]["unit"])) * line["price"] <= line["target"] * 1.25]  # fmt: skip
        if not candidates:
            candidates = [line for line in lines if line["price"] * _step(line["product"]["unit"]) <= left + 1e-9
                          and line["qty"] + _step(line["product"]["unit"]) <= line["available"]]  # fmt: skip
        if not candidates:
            break
        best = max(candidates, key=lambda line: (line["rate"], -line["qty"] * line["price"] / max(line["target"], 1)))
        best["qty"] = round(best["qty"] + _step(best["product"]["unit"]), 3)

    out = [{"productId": line["product"]["id"], "name": line["product"]["name"].split(" (")[0], "unit": line["product"]["unit"],
            "qty": line["qty"], "unitPrice": line["price"], "lineTotal": round2(line["qty"] * line["price"]),
            "margin": round2(line["qty"] * (line["price"] - line["cost"]))}
           for line in lines if line["qty"] > 0]  # fmt: skip
    total = round2(sum(line["lineTotal"] for line in out))
    return {"clientId": client_id, "budget": budget, "lines": out, "total": total, "budgetUsedPct": round(100 * total / budget, 1),
            "margin": round2(sum(line["margin"] for line in out))}  # fmt: skip
