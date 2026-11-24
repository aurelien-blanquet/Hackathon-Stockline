"""
Achat groupé par bon de commande provisoire: the first customer's purchase order goes out AT ONCE (a draft, as
always); when another customer then needs the same product, that draft is IMPROVED instead of a second one being
added: one negotiation (market/express.negotiate, learned levers included) for the summed quantity, a lower price
thanks to the bigger lot (strategy.volume_tier: 1,5 % per doubling, ≤ 5 %), one delivery.

    1st customer  → draft purchase order 10,5 kg at the producer kept                 (provisional)
    2nd customer  → the same order becomes 21 kg, renegotiated: a lower price per kg    (improved)
    3rd customer  → 31,5 kg, lower again …

No waiting, no peak-hour rule: every order exists in the ERP from the first yes (a restart loses nothing), and the
grouping happens whenever a next customer comes while the order is still a DRAFT (not yet sent to the producer) and
younger than GROUP_MAX_AGE_H. If the same producer keeps the bigger lot, its line is updated (quantity, price); if
another one is better, the old draft is cancelled and the new one created. A producer must deliver in time for EVERY
customer of the group (only the producers in time for all of them are asked).

Nothing changes for the customers: their price and day are those said during the call; the gain is ours (margin)
and shown on the screens (« Achat groupé : 3 clients, acheté seul 409,61 € → ensemble 395,33 € »).
GROUPING=0 turns it off (one purchase order per customer, as before).
"""

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from app.config import env
from app.tools import ErpClient

GROUPING = env("GROUPING", "1").lower() not in ("0", "false", "off", "no")
GROUP_MAX_AGE_H = float(env("GROUP_MAX_AGE_H", "4"))


@dataclass
class Demand:
    sourcing_id: str
    client_id: str | None
    qty: float  # what this customer needs from the producers
    solo_total: float  # its own negotiation's purchase total (what buying it alone costs)


@dataclass
class Group:
    id: str
    product_id: str
    name: str
    unit: str
    opened: float = field(default_factory=time.monotonic)
    demands: list[Demand] = field(default_factory=list)
    suppliers: set[str] = field(default_factory=set)  # producers in time for EVERY customer of the group
    orders: list[dict] = field(default_factory=list)  # the provisional purchase orders (ERP drafts)
    result: dict | None = None


GROUPS: dict[str, Group] = {}  # product id → the group still open to newcomers
DONE: list[dict] = []  # the last improvements (GET /market/pools)


async def order(erp: ErpClient, s: Any) -> dict | None:
    """The caller said yes. Returns the purchase orders (created, or the group's improved); None = grouping off.
    `s` is an express.Sourcing (not imported: express imports this module)."""
    from . import express

    if not GROUPING:
        return None
    if s.grouped and s.orders:  # the yes repeated
        return {"orders": s.orders, "alreadyPlaced": True}
    g = GROUPS.get(s.line.product_id)
    common = (g.suppliers & set(s.profiles)) if g else set()
    if g and common and time.monotonic() - g.opened < GROUP_MAX_AGE_H * 3600 and await _still_drafts(erp, g):
        try:
            return await _improve(erp, g, s, common)
        except Exception as e:  # the group cannot take it: this customer is bought alone (a group of its own)
            print(f"[group] not grouped ({e}): bought alone", flush=True)
    placed = await express.place_orders(erp, s.id, group=False)
    g = GROUPS[s.line.product_id] = Group(uuid.uuid4().hex[:8], s.line.product_id, s.line.name, s.line.unit,
                                          demands=[Demand(s.id, s.client_id, s.line.need, s.script.decision.total)],
                                          suppliers=set(s.profiles), orders=list(s.orders))  # fmt: skip
    s.grouped = g.id
    return {**placed, "provisional": True, "note": "Bon de commande provisoire : il sera amélioré si un autre client prend le même produit."}


async def _still_drafts(erp: ErpClient, g: Group) -> bool:
    """Every provisional order is still a draft (not sent to the producer): it may still change."""
    try:
        for o in g.orders:
            if o.get("id") and (await erp.get(f"/api/purchase-orders/{o['id']}")).get("status") != "draft":
                return False
        return True
    except Exception:
        return False


async def _improve(erp: ErpClient, g: Group, s: Any, common: set[str]) -> dict:
    """One negotiation for the summed lot with the producers in time for everyone, then the provisional orders are
    updated (same producer: its line) or replaced (another producer is better for the bigger lot)."""
    from . import express, levers

    members = [express.SOURCINGS[d.sourcing_id] for d in g.demands if d.sourcing_id in express.SOURCINGS] + [s]
    demands = [*g.demands, Demand(s.id, s.client_id, s.line.need, s.script.decision.total)]
    total = round(sum(d.qty for d in demands), 3)
    profiles = {sid: p for m in members for sid, p in m.profiles.items() if sid in common}
    line = replace(s.line, need=total, ref_qty=total / len(demands))
    script = express.negotiate([line], profiles, seed=f"group|{g.id}|{len(demands)}", urgent=True, memory=levers.MEMORY)
    d = script.decision
    if not d.allocations or d.covered + 1e-9 < total:
        raise LookupError("le lot groupé n'est pas couvert")
    levers.MEMORY.learn(script)
    arrivals = {sid: a for m in members for sid, a in m.arrivals.items()}
    clients = ", ".join(sorted({m.client_id or "client" for m in members}))
    note = f"Achat groupé ({len(demands)} clients : {clients}) : bon provisoire amélioré par l'agent achats"
    by_supplier: dict[str, list] = {}
    for a in d.allocations:
        by_supplier.setdefault(a.supplier_id, []).append(a)
    kept = {o.get("supplierId"): o for o in g.orders}
    orders = []
    sid = next(iter(by_supplier)) if len(by_supplier) == 1 else None
    if sid and len(g.orders) == 1 and sid in kept:  # the same producer keeps the bigger lot: its line is updated
        po = await erp.get(f"/api/purchase-orders/{kept[sid]['id']}")
        pl = next(x for x in po.get("lines") or [] if x.get("productId") == g.product_id)
        a = by_supplier[sid][0]
        po = await erp.patch(f"/api/purchase-orders/{po['id']}/lines/{pl['id']}", {"qty": a.qty, "unitPrice": a.price})
        try:
            await erp.patch(f"/api/purchase-orders/{po['id']}", {"note": note})
        except Exception:  # the note is a nicety
            pass
        orders.append({"id": po["id"], "supplierId": sid, "number": po.get("number"), "supplier": profiles[sid].name,
                       "totalHt": po.get("totalHt"), "group": g.id, "updated": True})  # fmt: skip
    else:  # another producer (or a split) is better for the bigger lot: the old drafts go, new ones replace them
        for o in g.orders:
            if o.get("id"):
                await erp.post(f"/api/purchase-orders/{o['id']}/cancel")
        for sup, allocs in by_supplier.items():
            po = await erp.post("/api/purchase-orders", {"supplierId": sup, "expectedDate": arrivals[sup], "note": note,
                                                         "lines": [{"productId": a.product_id, "qty": a.qty, "unitPrice": a.price} for a in allocs]})  # fmt: skip
            orders.append({"id": po.get("id"), "supplierId": sup, "number": po.get("number"), "supplier": profiles[sup].name,
                           "totalHt": po.get("totalHt"), "group": g.id})  # fmt: skip
    g.demands, g.suppliers, g.orders = demands, common, orders
    for m in members:
        m.orders, m.grouped = orders, g.id
    solo = round(sum(x.solo_total for x in demands), 2)
    saved = round(solo - d.total, 2)
    g.result = {"groupId": g.id, "product": express.short(g.name), "clients": len(demands), "qty": total, "unit": line.unit,
                "soloTotal": solo, "groupTotal": round(d.total, 2), "saved": saved, "savedPct": round(100 * saved / solo, 1) if solo else 0.0,
                "orders": orders}  # fmt: skip
    DONE.insert(0, g.result)
    del DONE[10:]
    r = express.ExpressRound(express.Sourcing(f"g{g.id}{len(demands)}", None, line, profiles, script, arrivals), erp=erp,
                             title=f"Achat groupé : {express.short(g.name)} — {len(demands)} clients",
                             need_by=min(m.deliver_by or "9999" for m in members), pace=express.EXPRESS_PACE, group=g.result)  # fmt: skip
    express.ROUNDS[r.id] = r
    express.spawn(r.run())
    g.result["roundId"] = r.id
    print(f"[group] {g.result}", flush=True)
    return {"orders": orders, "grouped": True, "clients": len(demands), "saved": saved,
            "note": "Bon de commande groupé avec un autre client : n'en parle pas au client, son prix et son jour ne changent pas."}  # fmt: skip


def snapshot() -> dict:
    return {"grouping": GROUPING,
            "open": [{"groupId": g.id, "product": g.name, "clients": len(g.demands), "qty": round(sum(d.qty for d in g.demands), 3),
                      "orders": g.orders} for g in GROUPS.values()],
            "done": DONE}  # fmt: skip
