"""
Volume discount on a big order: what the phone agent may offer, decided here (never by the model).

House rules (data/context/05-prix-et-credit.md): « commerciaux jusqu'à 5 %, au-delà Jean-Marc » and the resolution
order « prix négocié client > règle de prix > prix liste ». The volume rules of the price list (priceRules) are already
in the resolved price; this is the extra a salesperson grants on a big line, within their limit:

    big line        ≥ BIG_TOTAL € HT, or ≥ 3× the client's usual quantity (and ≥ 500 €)
    steps           1 500 € → 2 %, 3 000 € → 3 %, 6 000 € → 4 %, 10 000 € → 5 %; +1 point for ≥ 3× the usual
    caps            5 % (salespeople) ; 2 % on a price already negotiated for this client ; never below cost + 12 %
    no discount     blocked client, overdue invoice (« on règle d'abord »), normal volume
    above 5 % asked → needsManager: Jean-Marc validates

The answer never contains the cost, the margin or the floor: only the price the client may be offered.
"""

from __future__ import annotations

from app import crud
from app.core.db import Doc
from app.core.utils import round2
from app.services import clients, pricing

LIMIT_PCT = 5.0
NEGOTIATED_CAP_PCT = 2.0
MIN_MARGIN = 0.12
BIG_TOTAL = 1500.0
STEPS = [(10000.0, 5.0), (6000.0, 4.0), (3000.0, 3.0), (1500.0, 2.0)]
MANAGER = "Jean-Marc"


def volume_offer(client_id: str, product_id: str, qty: float, requested_pct: float | None = None) -> Doc:
    client = crud.clients.require(client_id)
    r = pricing.resolve_price(client_id, product_id, qty)
    price, cost = float(r["price"]), float(r.get("cost") or 0)
    total = round2(price * qty)
    usual = next((u for u in clients.usual_basket(client_id) if u["productId"] == product_id), None)
    avg = float(usual["avgQty"]) if usual else 0.0
    huge = avg > 0 and qty >= 3 * avg
    base = {"listUnitPrice": price, "qty": qty, "lineTotal": total, "maxPct": LIMIT_PCT, "manager": MANAGER}

    def no(reason: str, say: str) -> Doc:
        return {**base, "eligible": False, "pct": 0.0, "unitPrice": price, "reason": reason, "say": say,
                "needsManager": bool(requested_pct and requested_pct > LIMIT_PCT)}  # fmt: skip

    if client.get("status") == "blocked":
        return no("blocked", "Pas de remise possible tant que le compte est bloqué.")
    if (clients.client_balances(client_id).get("overdue") or 0) > 0:
        return no("overdue", "Une facture est en retard : on la règle d'abord, et on reparle du prix ensuite.")
    if not (total >= BIG_TOTAL or (huge and total >= 500)):
        return no("normal_volume", "C'est déjà son tarif pour ce volume.")

    pct = next((p for floor, p in STEPS if total >= floor), 0.0) + (1.0 if huge else 0.0)
    if r.get("source") not in ("list", "rule"):  # a price already negotiated for this client: a smaller gesture
        pct = min(pct, NEGOTIATED_CAP_PCT)
    if cost > 0:  # never below cost + MIN_MARGIN
        pct = min(pct, max(0.0, (1 - cost * (1 + MIN_MARGIN) / price) * 100))
    pct = min(LIMIT_PCT, int(pct * 2) / 2)  # half points, rounded down
    if requested_pct is not None and 0 < requested_pct < pct:
        pct = int(requested_pct * 2) / 2  # never more than asked
    if pct <= 0:
        return no("margin", "C'est déjà son meilleur prix sur ce produit.")
    unit = round2(price * (1 - pct / 100))
    out = {**base, "eligible": True, "pct": pct, "unitPrice": unit, "lineTotalAfter": round2(unit * qty),
           "saved": round2((price - unit) * qty), "condition": "pour cette commande, livrée en une fois",
           "needsManager": bool(requested_pct and requested_pct > LIMIT_PCT), "reason": "volume"}  # fmt: skip
    return out
