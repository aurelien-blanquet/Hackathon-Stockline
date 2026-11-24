"""
« Le comité de prix » during a call: four agents work AT THE SAME TIME on a big line or a price objection, then the
ERP's arbiter (backend services/deals.py) picks the offers. The model only says the conclusion; the staff screen shows
the debate (WS agent_deal).

    buyer    negotiates this volume with every producer at once (market/express.source, volume mode; replayed live)
    stock    lots and expiry dates: what must be sold first
    credit   outstanding, overdue, status: can we be generous, is the order safe
    sales    the client's usual quantity, price source, delivery days

The panel (costs, margins, producers) is kept in DEALS for the screen; the model gets customer-safe fields only.
"""

import asyncio
import time
import uuid
from datetime import date

from app.tools import ErpClient

DEALS: dict[str, dict] = {}  # deal id → {panel, negotiatedCost, sourcingId, clientId, productId, qty}
DEALS_MAX = 30
UNIT = {"kg": "kg", "piece": "pièces", "liter": "L", "box": "cartons", "dozen": "douzaines"}


def _eur(x: float | None) -> str:
    return "—" if x is None else f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def _qty(x: float | None, unit: str) -> str:
    if x is None:
        return "—"
    n = f"{x:,.0f}" if float(x).is_integer() else f"{x:,.1f}"
    return f"{n.replace(',', ' ').replace('.', ',')} {UNIT.get(unit, unit)}"


async def _timed(coro):
    t0 = time.perf_counter()
    try:
        out = await coro
    except Exception as e:  # noqa: BLE001 — an agent failing never breaks the deal: the arbiter works without it
        out = {"error": f"{type(e).__name__}: {e}"}
    return out, int((time.perf_counter() - t0) * 1000)


async def buyer(erp: ErpClient, client_id: str, product_id: str, qty: float, delivery_date: str | None) -> dict:
    from app.market.express import source

    src = await source(erp, product_id, qty, client_id, delivery_date, replay=True, volume=True)
    offers = src.get("offers") or []
    best = min(offers, key=lambda o: o["unitPrice"]) if offers else None
    usual = src.get("usualCost")
    blended = src.get("blendedCost")
    gain = blended is not None and usual is not None and blended < usual
    if best:
        line = f"{best['supplier']} : {_eur(best['openingPrice'])} → {_eur(best['unitPrice'])}"
        line += f" · coût moyen {_eur(usual)} → {_eur(blended)}" if gain else f" · pas mieux que notre coût ({_eur(usual)})"
    else:
        line = src.get("say") or "aucun producteur disponible"
    return {"line": line, "negotiatedCost": blended if gain else None, "sourcingId": src.get("sourcingId") if gain else None,
            "producers": len(offers), "roundId": src.get("roundId")}  # fmt: skip


async def stock_agent(erp: ErpClient, product_id: str, qty: float) -> dict:
    p = await erp.get(f"/api/products/{product_id}")
    s, unit = p.get("stock") or {}, p.get("unit") or "kg"
    today = date.fromisoformat((await erp.get("/api/meta")).get("today"))
    soon = [lot for lot in s.get("lots") or [] if (date.fromisoformat(lot["expiresAt"]) - today).days <= 21]
    exp = sum(lot["qtyRemaining"] for lot in soon)
    line = f"{_qty(s.get('available'), unit)} disponibles"
    line += f" · {_qty(exp, unit)} expirent avant le {soon[-1]['expiresAt'][8:10]}/{soon[-1]['expiresAt'][5:7]} → à écouler" if exp else " · pas de date courte"
    if (s.get("available") or 0) < qty:
        line += " · stock insuffisant"
    return {"line": line, "expiringQty": exp}


async def credit_agent(erp: ErpClient, client_id: str) -> dict:
    c = await erp.get(f"/api/clients/{client_id}")
    if c.get("status") == "blocked":
        return {"line": "compte bloqué → aucune remise, aucune commande", "ok": False}
    if (c.get("overdue") or 0) > 0:
        return {"line": f"retard de paiement {_eur(c['overdue'])} → pas de remise", "ok": False}
    room = (c.get("creditLimit") or 0) - (c.get("outstanding") or 0)
    return {"line": f"bon payeur · encours {_eur(c.get('outstanding'))} / {_eur(c.get('creditLimit'))} (reste {_eur(room)})", "ok": True}


async def sales_agent(erp: ErpClient, client_id: str, product_id: str, qty: float) -> dict:
    c = await erp.get(f"/api/clients/{client_id}")
    u = next((x for x in c.get("usual") or [] if x["productId"] == product_id), None)
    fr = {"mon": "lun", "tue": "mar", "wed": "mer", "thu": "jeu", "fri": "ven", "sat": "sam", "sun": "dim"}
    days = ", ".join(fr.get(d, d) for d in c.get("deliveryDays") or []) or "—"
    if u:
        ratio = qty / u["avgQty"] if u["avgQty"] else 0
        line = f"habituel {_qty(u['avgQty'], u.get('unit') or 'kg')} · demande ×{ratio:.0f}".replace(".", ",")
    else:
        line = "nouveau produit pour ce client"
    return {"line": f"{line} · livré {days}"}


async def run(erp: ErpClient, client_id: str, product_id: str, qty: float, delivery_date: str | None = None,
              objection: bool = True) -> dict:  # fmt: skip
    """The four agents in parallel, then the arbiter. Returns the deal (panel + options)."""
    t0 = time.perf_counter()
    (b, tb), (s, ts), (c, tc), (v, tv) = await asyncio.gather(
        _timed(buyer(erp, client_id, product_id, qty, delivery_date)),
        _timed(stock_agent(erp, product_id, qty)),
        _timed(credit_agent(erp, client_id)),
        _timed(sales_agent(erp, client_id, product_id, qty)),
    )
    neg = b.get("negotiatedCost")
    q = {"clientId": client_id, "productId": product_id, "qty": qty, "objection": str(objection).lower(),
         **({"negotiatedCost": round(neg, 4)} if neg else {})}  # fmt: skip
    arb = await erp.get("/api/prices/deal-options", q)
    deal_id = uuid.uuid4().hex[:8]
    options = {o["key"]: o for o in arb["options"]}
    chosen = options[arb["chosen"]]
    panel = {
        "dealId": deal_id, "product": arb["productName"].split(" (")[0], "askedQty": qty,
        "agents": [
            {"name": "Achat", "line": b.get("line") or b.get("error", "—"), "ms": tb},
            {"name": "Stock", "line": s.get("line") or s.get("error", "—"), "ms": ts},
            {"name": "Crédit", "line": c.get("line") or c.get("error", "—"), "ms": tc},
            {"name": "Ventes", "line": v.get("line") or v.get("error", "—"), "ms": tv},
        ],
        "options": arb["options"], "chosen": arb["chosen"], "alternative": arb["alternative"],
        "decision": f"option {chosen['key']} : {_qty(chosen['qty'], chosen['unit'])} à {_eur(chosen['unitPrice'])}"
                    f" · marge {_eur(chosen['margin'])}" + (f" · perte évitée {_eur(chosen['wasteAvoided'])}" if chosen["wasteAvoided"] else ""),
        "ms": int((time.perf_counter() - t0) * 1000), "roundId": b.get("roundId"),
    }  # fmt: skip
    DEALS[deal_id] = {"panel": panel, "negotiatedCost": neg, "sourcingId": b.get("sourcingId"), "clientId": client_id,
                      "productId": product_id, "qty": qty, "options": options, "blocked": arb.get("blocked")}  # fmt: skip
    for old in list(DEALS)[:-DEALS_MAX]:
        DEALS.pop(old, None)
    return DEALS[deal_id]
