"""Purchase orders (commandes fournisseur):

    draft ──send──▶ sent ──receive──▶ partially_received ──receive──▶ received
    draft | sent | partially_received ──cancel──▶ cancelled (lots already received stay in stock)

Each receipt creates one Lot per line received (expiry = today + product.shelfLifeDays) + a "receipt"
movement. Lines are editable in draft only; expectedDate/note in draft or sent. A draft may have no
lines (sending needs ≥ 1).
"""

from __future__ import annotations

import math

import uuid

from app import crud
from app.core.activity import Ctx, log_event, now, today
from app.core.db import Doc, per_data_version, transactional
from app.core.listing import Key, ListQuery, apply_sort, count_by, respond, split_set, sum_of
from app.core.errors import bad_request, conflict
from app.core.utils import add_days, cmp, collate_key, de, fmt_eur, js_round, js_str, normalize, round2, round3, sort_by, total
from app.services import clients
from app.services.stock import add_lot

STATUS_FR = {
    "draft": "brouillon",
    "sent": "envoyée",
    "partially_received": "partiellement reçue",
    "received": "reçue",
    "cancelled": "annulée",
}


def _guard(po: Doc, allowed: list[str], action: str) -> None:
    if po["status"] not in allowed:
        expected = " ou ".join(STATUS_FR[s] for s in allowed)
        raise conflict(
            "invalid_transition",
            f"Impossible {de(action)} {po['number']} : elle est {STATUS_FR[po['status']]} (attendu : {expected})",
        )


def _po_total(lines: list[Doc]) -> float:
    return round2(total(l["qty"] * l["unitPrice"] for l in lines))


def _save(po: Doc) -> Doc:
    """Save a purchase order, recomputing its total."""
    return crud.purchase_orders.put({**po, "totalHt": _po_total(po["lines"])})


def po_warnings(po: Doc) -> list[Doc]:
    """Non-blocking warnings for a purchase order still editable (draft/sent)."""
    if po["status"] not in ("draft", "sent"):
        return []
    supplier = crud.suppliers.get(po["supplierId"])
    if not supplier:
        return []
    warnings: list[Doc] = []
    po_total = _po_total(po["lines"])
    if po["lines"] and supplier["minOrderAmount"] > 0 and po_total < supplier["minOrderAmount"]:
        warnings.append({
            "code": "below_min_order",
            "message": f"Commande sous le minimum de {supplier['name']} : {fmt_eur(po_total)} HT pour un minimum de {fmt_eur(supplier['minOrderAmount'])}",
        })  # fmt: skip
    for l in po["lines"]:
        p = crud.products.get(l["productId"])
        name = p["name"] if p else l["productId"]
        sp = crud.supplier_prices.get(f"{supplier['id']}|{l['productId']}")
        if not sp:
            warnings.append({"code": "not_in_supplier_catalog", "productId": l["productId"], "message": f"{name} n'est pas au catalogue de {supplier['name']}"})
        elif l["unitPrice"] > sp["price"] * 1.1:
            pct = js_round((l["unitPrice"] / sp["price"] - 1) * 100)
            warnings.append({
                "code": "price_above_usual",
                "productId": l["productId"],
                "message": f"{name} acheté {fmt_eur(l['unitPrice'])}, soit +{pct} % au-dessus du prix habituel de {supplier['name']} ({fmt_eur(sp['price'])})",
            })  # fmt: skip
    return warnings


def po_summary(po: Doc) -> Doc:
    supplier = crud.suppliers.get(po["supplierId"])
    summary = {k: v for k, v in po.items() if k != "lines"}
    return {**summary, "supplierName": supplier["name"] if supplier else "?", "lineCount": len(po["lines"])}


def _supplier_name(supplier_id: str) -> str:
    s = crud.suppliers.get(supplier_id)
    return s["name"] if s else "?"


@per_data_version
def pos_newest_first() -> list[Doc]:
    return sorted(crud.purchase_orders.rows.values(), key=lambda po: po["createdAt"], reverse=True)


PO_SORTS: dict[str, Key] = {
    "number": lambda po: po["number"],
    "supplier": lambda po: collate_key(_supplier_name(po["supplierId"])),
    "date": lambda po: po.get("expectedDate"),
    "createdAt": lambda po: po["createdAt"],
    "lines": lambda po: len(po["lines"]),
    "total": lambda po: po["totalHt"],
    "status": lambda po: po["status"],
}


def list_purchase_orders(lq: ListQuery, status: str | None = None, supplier_id: str | None = None,
                         date: str | None = None, q: str | None = None) -> list[Doc] | Doc:  # fmt: skip
    """GET /api/purchase-orders — newest first. Envelope extras: counts per status (ignoring `status`), sums.totalHt."""
    statuses = split_set(status)
    nq = normalize(q) if q else None
    base = [
        po for po in pos_newest_first()
        if (not supplier_id or po["supplierId"] == supplier_id)
        and (not date or po.get("expectedDate") == date)
        and (not nq or nq in f"{normalize(po['number'])} {normalize(_supplier_name(po['supplierId']))}")
    ]  # fmt: skip
    rows = [po for po in base if po["status"] in statuses] if statuses else base
    rows = apply_sort(rows, lq, PO_SORTS)
    return respond(rows, lq, po_summary, lambda: {
        "counts": count_by(base, lambda po: po["status"]),
        "sums": sum_of(rows, totalHt=lambda po: po["totalHt"]),
    })


def po_detail(id: str) -> Doc:
    po = crud.purchase_orders.require(id)
    lines = []
    for l in po["lines"]:
        p = crud.products.get(l["productId"])
        lines.append({**l, "productName": p["name"] if p else "?", "unit": p["unit"] if p else ""})
    return {
        **po,
        "supplier": crud.suppliers.require(po["supplierId"]),
        "lines": lines,
        "lots": crud.lots.filter(lambda lot: lot.get("purchaseOrderId") == id),
        "warnings": po_warnings(po),
    }


def purchase_price(supplier_id: str, product_id: str) -> float:
    """Purchase price: supplier price list > product reference cost."""
    sp = crud.supplier_prices.get(f"{supplier_id}|{product_id}")
    return sp["price"] if sp else crud.products.require(product_id)["cost"]


def _build_line(supplier_id: str, input: Doc) -> Doc:
    crud.products.require(input["productId"])
    if not input["qty"] > 0:
        raise bad_request("invalid_qty", "La quantité doit être positive")
    unit_price = input.get("unitPrice")
    if unit_price is not None and unit_price < 0:
        raise bad_request("invalid_price", "Le prix doit être positif")
    return {
        "id": f"pol_{uuid.uuid4().hex[:8]}",
        "productId": input["productId"],
        "qty": input["qty"],
        "unitPrice": round2(unit_price if unit_price is not None else purchase_price(supplier_id, input["productId"])),
        "receivedQty": 0,
    }


@transactional
def create_purchase_order(ctx: Ctx, input: Doc) -> Doc:
    """Creates a draft. `lines` may be empty (draft started right after picking the supplier)."""
    supplier = crud.suppliers.require(input["supplierId"])
    lines = [_build_line(supplier["id"], l) for l in input.get("lines") or []]
    t = today()
    po = {
        "id": crud.purchase_orders.next_id("po_"),
        "number": crud.purchase_orders.next_number("ACH", t[:4]),
        "supplierId": supplier["id"],
        "status": "draft",
        "expectedDate": input.get("expectedDate") or add_days(t, supplier["leadTimeDays"]),
        "lines": lines,
        "totalHt": 0,
        "createdAt": now(),
        **({"note": input["note"]} if input.get("note") else {}),
    }
    saved = _save(po)
    below = lines and saved["totalHt"] < supplier["minOrderAmount"]
    min_note = f" (sous le minimum de {fmt_eur(supplier['minOrderAmount'])})" if below else ""
    log_event(ctx, "purchase_order.created", "purchase_order", po["id"],
              f"Commande fournisseur {po['number']} créée chez {supplier['name']} ({len(lines)} ligne(s), {fmt_eur(saved['totalHt'])} HT){min_note}")  # fmt: skip
    return po_detail(po["id"])


@transactional
def update_purchase_order(ctx: Ctx, id: str, patch: Doc) -> Doc:
    po = crud.purchase_orders.require(id)
    _guard(po, ["draft", "sent"], "modifier")
    _save({**po, **patch})
    what = []
    if patch.get("expectedDate"):
        what.append(f"livraison attendue le {patch['expectedDate']}")
    if "note" in patch:
        what.append("note")
    log_event(ctx, "purchase_order.updated", "purchase_order", id,
              f"Commande fournisseur {po['number']} modifiée ({', '.join(what) or 'aucun changement'})")  # fmt: skip
    return po_detail(id)


@transactional
def add_purchase_line(ctx: Ctx, id: str, input: Doc) -> Doc:
    po = crud.purchase_orders.require(id)
    _guard(po, ["draft"], "ajouter une ligne à")
    line = _build_line(po["supplierId"], input)
    _save({**po, "lines": [*po["lines"], line]})
    p = crud.products.require(line["productId"])
    log_event(ctx, "purchase_order.line_added", "purchase_order", id,
              f"{js_str(line['qty'])} {p['unit']} de {p['name']} ajouté(s) à {po['number']} ({fmt_eur(line['unitPrice'])})")  # fmt: skip
    return po_detail(id)


@transactional
def update_purchase_line(ctx: Ctx, id: str, line_id: str, patch: Doc) -> Doc:
    po = crud.purchase_orders.require(id)
    _guard(po, ["draft"], "modifier une ligne de")
    line = next((l for l in po["lines"] if l["id"] == line_id), None)
    if not line:
        raise bad_request("unknown_line", f"Ligne {line_id} introuvable sur {po['number']}")
    updated = {**line, **({"qty": patch["qty"]} if "qty" in patch else {})}
    if patch.get("productId") and patch["productId"] != line["productId"]:
        rebuilt = _build_line(po["supplierId"], {"productId": patch["productId"], "qty": updated["qty"], "unitPrice": patch.get("unitPrice")})
        updated = {**updated, "productId": rebuilt["productId"], "unitPrice": rebuilt["unitPrice"]}
    elif "unitPrice" in patch:
        updated["unitPrice"] = patch["unitPrice"]
    if not updated["qty"] > 0:
        raise bad_request("invalid_qty", "La quantité doit être positive")
    if updated["unitPrice"] < 0:
        raise bad_request("invalid_price", "Le prix doit être positif")
    updated["unitPrice"] = round2(updated["unitPrice"])
    _save({**po, "lines": [updated if l["id"] == line_id else l for l in po["lines"]]})
    p = crud.products.get(updated["productId"])
    log_event(ctx, "purchase_order.line_updated", "purchase_order", id,
              f"Ligne {p['name'] if p else updated['productId']} modifiée sur {po['number']} "
              f"({js_str(updated['qty'])} {p['unit'] if p else ''} à {fmt_eur(updated['unitPrice'])})")  # fmt: skip
    return po_detail(id)


@transactional
def delete_purchase_line(ctx: Ctx, id: str, line_id: str) -> Doc:
    """Removing the last line is allowed: a draft may be empty."""
    po = crud.purchase_orders.require(id)
    _guard(po, ["draft"], "retirer une ligne de")
    line = next((l for l in po["lines"] if l["id"] == line_id), None)
    if not line:
        raise bad_request("unknown_line", f"Ligne {line_id} introuvable sur {po['number']}")
    _save({**po, "lines": [l for l in po["lines"] if l["id"] != line_id]})
    p = crud.products.get(line["productId"])
    log_event(ctx, "purchase_order.line_removed", "purchase_order", id, f"{p['name'] if p else line['productId']} retiré de {po['number']}")
    return po_detail(id)


def supplier_usual_basket(supplier_id: str) -> list[Doc]:
    """What we usually buy from a supplier: purchase orders created in the last 60 days
    (draft and cancelled excluded) — same algorithm as the client usual basket."""
    crud.suppliers.require(supplier_id)
    since = add_days(today(), -60)
    pos = crud.purchase_orders.filter(
        lambda po: po["supplierId"] == supplier_id and po["status"] not in ("draft", "cancelled") and po["createdAt"][:10] >= since
    )
    pos = sort_by(pos, lambda a, b: cmp(a["createdAt"], b["createdAt"]))
    return clients.usual_basket_of(pos, lambda po: po["createdAt"][:10])


@transactional
def send_purchase_order(ctx: Ctx, id: str) -> Doc:
    po = crud.purchase_orders.require(id)
    _guard(po, ["draft"], "envoyer")
    if not po["lines"]:
        raise conflict("empty_order", f"La commande fournisseur {po['number']} n'a aucune ligne")
    crud.purchase_orders.put({**po, "status": "sent"})
    supplier = crud.suppliers.get(po["supplierId"])
    log_event(ctx, "purchase_order.sent", "purchase_order", id, f"Commande {po['number']} envoyée à {supplier['name'] if supplier else '?'}")
    return po_detail(id)


@transactional
def receive_purchase_order(ctx: Ctx, id: str, received: list[Doc] | None = None) -> Doc:
    """Record a receipt. `receivedQty` is the quantity received NOW (added to what was already received).
    Without lines, everything still outstanding is received."""
    po = crud.purchase_orders.require(id)
    _guard(po, ["sent", "partially_received"], "réceptionner")
    if received:
        by_line = {r["lineId"]: r["receivedQty"] for r in received}
    else:
        by_line = {l["id"]: max(0, round3(l["qty"] - l["receivedQty"])) for l in po["lines"]}
    for line_id, qty in by_line.items():
        if not any(l["id"] == line_id for l in po["lines"]):
            raise bad_request("unknown_line", f"Ligne {line_id} introuvable sur {po['number']}")
        if qty < 0:
            raise bad_request("invalid_qty", "Quantité reçue négative")
    lot_count = 0
    lines = []
    for l in po["lines"]:
        qty = by_line.get(l["id"], 0)
        if qty <= 0:
            lines.append(l)
            continue
        add_lot(crud.products.require(l["productId"]), qty, "receipt",
                {"refType": "purchase_order", "refId": po["id"], "supplierId": po["supplierId"], "purchaseOrderId": po["id"]})  # fmt: skip
        lot_count += 1
        lines.append({**l, "receivedQty": round3(l["receivedQty"] + qty)})
    if not lot_count:
        raise bad_request("nothing_received", "Aucune quantité reçue")
    status = "received" if all(l["receivedQty"] >= l["qty"] for l in lines) else "partially_received"
    crud.purchase_orders.put({**po, "lines": lines, "status": status})
    kind = "complète" if status == "received" else "partielle"
    log_event(ctx, "purchase_order.received", "purchase_order", id,
              f"Réception {kind} de {po['number']} : {lot_count} lot(s) entré(s) en stock")  # fmt: skip
    return po_detail(id)


@transactional
def cancel_purchase_order(ctx: Ctx, id: str) -> Doc:
    po = crud.purchase_orders.require(id)
    _guard(po, ["draft", "sent", "partially_received"], "annuler")
    crud.purchase_orders.put({**po, "status": "cancelled"})
    log_event(ctx, "purchase_order.cancelled", "purchase_order", id, f"Commande fournisseur {po['number']} annulée")
    return po_detail(id)



# ───────── Sourcing needs (« le marché du matin »: what to buy, from whom) ─────────


def replenishment_needs(today: str, days: int = 28, cover_days: float = 7, max_lines: int = 60) -> Doc:
    """The morning replenishment (« réassort du matin »): every product must hold AT LEAST an average of its sales.
    avg/day = units sold over the `days` days before `today` (orders not draft/cancelled, by delivery date) / days;
    target = avg/day × cover_days (default: one average week); need = target − (available + incoming), rounded UP
    (whole units; kg to the half). For each short product: who can supply it, as sourcing_needs. Biggest needs (by
    value at cost) first, at most `max_lines`. Also returns how many products were checked and how many are below."""
    from datetime import date, timedelta

    from app.services.stock import stock_levels

    end = date.fromisoformat(today[:10])
    start = (end - timedelta(days=days)).isoformat()
    sold: dict[str, float] = {}
    for o in crud.orders.filter(lambda o: start <= o["deliveryDate"] < end.isoformat() and o["status"] not in ("draft", "cancelled")):
        for line in o["lines"]:
            sold[line["productId"]] = sold.get(line["productId"], 0) + line["qty"]
    levels = stock_levels()
    suppliers = crud.suppliers.all()
    prices = {(p["supplierId"], p["productId"]): p["price"] for p in crud.supplier_prices.all()}
    lines: list[Doc] = []
    for pid, qty in sold.items():
        p = crud.products.get(pid)
        if not p or not p.get("active", True):
            continue
        avg = qty / days
        target = avg * cover_days
        level = levels.get(pid) or {}
        have = (level.get("available") or 0) + (level.get("incoming") or 0)
        need = target - have
        if need <= 0:
            continue
        need = math.ceil(need * 2) / 2 if p["unit"] in ("kg", "liter") else float(math.ceil(need - 1e-9))
        who = [
            {"supplierId": s["id"], "name": s["name"], **({"price": prices[(s["id"], pid)]} if (s["id"], pid) in prices else {})}
            for s in suppliers
            if p["category"] in (s.get("categories") or [])
        ]
        if not who:
            continue
        lines.append({
            "productId": pid, "name": p["name"], "unit": p["unit"], "category": p["category"], "cost": p["cost"],
            "avgPerDay": round3(avg), "target": round3(target), "available": level.get("available") or 0,
            "incoming": level.get("incoming") or 0, "need": need, "suppliers": who,
        })
    lines.sort(key=lambda l: -l["need"] * l["cost"])
    return {"today": end.isoformat(), "days": days, "coverDays": cover_days, "checked": len(sold), "below": len(lines),
            "lines": lines[:max_lines]}


def sourcing_needs(date_from: str, date_to: str, per_category: int = 2) -> Doc:
    """What we will lack over a period, by the sales of that same period (e.g. last year's Christmas week):
    need = units sold over [date_from, date_to] − (available + incoming). For each short product: who can supply it
    (suppliers whose categories include the product's, with their price-list price when they have one).
    Keeps the `per_category` biggest needs (by value at cost) of each category: one basket that touches every supplier."""
    from app.services.stock import stock_levels

    sold: dict[str, float] = {}
    for o in crud.orders.filter(lambda o: date_from <= o["deliveryDate"] <= date_to and o["status"] not in ("draft", "cancelled")):
        for line in o["lines"]:
            sold[line["productId"]] = sold.get(line["productId"], 0) + line["qty"]
    levels = stock_levels()
    suppliers = crud.suppliers.all()
    prices = {(p["supplierId"], p["productId"]): p["price"] for p in crud.supplier_prices.all()}
    lines: list[Doc] = []
    for pid, qty in sold.items():
        p = crud.products.get(pid)
        if not p or not p.get("active", True):
            continue
        level = levels.get(pid) or {}
        have = (level.get("available") or 0) + (level.get("incoming") or 0)
        need = qty - have
        if need <= 0:
            continue
        need = round(need) if p["unit"] != "kg" else round(need, 1)
        who = [
            {"supplierId": s["id"], "name": s["name"], **({"price": prices[(s["id"], pid)]} if (s["id"], pid) in prices else {})}
            for s in suppliers
            if p["category"] in (s.get("categories") or [])
        ]
        if not who:
            continue
        lines.append({
            "productId": pid, "name": p["name"], "unit": p["unit"], "category": p["category"], "cost": p["cost"],
            "sold": round3(qty), "available": level.get("available") or 0, "incoming": level.get("incoming") or 0,
            "need": need, "suppliers": who,
        })
    lines.sort(key=lambda l: -l["need"] * l["cost"])
    kept, per_cat = [], {}
    for line in lines:
        if per_cat.get(line["category"], 0) < per_category:
            per_cat[line["category"]] = per_cat.get(line["category"], 0) + 1
            kept.append(line)
    return {"from": date_from, "to": date_to, "lines": kept}


def product_sources(product_id: str) -> Doc:
    """One product, for an in-call buying round (« marché express »): its stock (available, incoming) and every supplier
    that can supply it (categories include the product's), with their price-list price when they have one."""
    from app.services.stock import stock_levels

    p = crud.products.require(product_id)
    level = stock_levels().get(product_id) or {}
    prices = {sp["supplierId"]: sp["price"] for sp in crud.supplier_prices.all() if sp["productId"] == product_id}
    who = [
        {"supplierId": s["id"], "name": s["name"], **({"price": prices[s["id"]]} if s["id"] in prices else {})}
        for s in crud.suppliers.all()
        if p["category"] in (s.get("categories") or []) or s["id"] in prices
    ]
    return {
        "productId": product_id, "name": p["name"], "unit": p["unit"], "category": p["category"], "cost": p["cost"],
        "price": p.get("price"), "available": level.get("available") or 0, "incoming": level.get("incoming") or 0,
        "suppliers": who,
    }
