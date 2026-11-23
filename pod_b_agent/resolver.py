"""Extraction -> OrderDraft: SKU resolution, unit conversion, history merge, stock,
substitutions, anomalies, upsell, confidence. Owned by Pod B. Deterministic and testable."""
from __future__ import annotations

import itertools
from datetime import date, timedelta
from typing import Optional

from shared_contracts.schemas import (
    Alert, AlertType, Candidate, LineSource, OrderDraft, OrderLine, OrderStatus, Severity,
    StockStatus, Substitution, Unit,
)

from .catalog import Catalog, Product, load_catalog
from .extraction import Extraction, Mention
from .extractor_rules import DAYS

REVIEW_THRESHOLD = 0.70
ANOMALY_HIGH, ANOMALY_LOW = 3.0, 0.25


# ───────── helpers ─────────
def convert(qty: Optional[float], unit: Optional[str], p: Product) -> tuple[Optional[float], bool]:
    """Spoken (qty, unit) -> quantity in the product's sell unit. Returns (qty, is_estimate)."""
    if qty is None:
        return None, False
    su = p.sell_unit.value
    if unit is None or unit == su:
        if unit is None and su == "kg" and "piece" in p.conversions:   # "deux bars" -> kg estimate
            f, est = p.conversions["piece"]
            return round(qty * f, 3), est
        return qty, False
    if unit == "g" and su == "kg":
        return qty / 1000, False
    if unit == "piece" and su in ("botte", "barquette"):
        return qty, False
    if unit in p.conversions:
        f, est = p.conversions[unit]
        return round(qty * f, 3), est
    return None, False


def find_history_order(customer: Optional[dict], ref: Optional[str], call_date: date) -> Optional[dict]:
    if not customer or not ref or not customer.get("orders"):
        return None
    orders = sorted(customer["orders"], key=lambda o: o["date"])
    if ref in DAYS:
        wd = DAYS.index(ref)
        delta = (call_date.weekday() - wd) % 7 or 7
        target = (call_date - timedelta(days=delta)).isoformat()
        for o in orders:
            if o["date"] == target:
                return o
    return orders[-1]


def usual_qty(customer: Optional[dict], sku: str) -> Optional[float]:
    if not customer:
        return None
    qs = [ln["qty"] for o in customer.get("orders", []) for ln in o["lines"] if ln["sku"] == sku]
    return sum(qs) / len(qs) if qs else None


# ───────── main ─────────
def resolve(ex: Extraction, call_id: str, customer: Optional[dict], call_date: date,
            catalog: Optional[Catalog] = None, stt_confidence: float = 0.92) -> OrderDraft:
    cat = catalog or load_catalog()
    ids = itertools.count(1)
    alerts: list[Alert] = []
    lines: dict[str, OrderLine] = {}       # key: sku, or "UNK:<text>" for unknown products

    def alert(t: AlertType, sev: Severity, msg: str, line_id: Optional[str] = None,
              action: Optional[str] = None, **data) -> None:
        alerts.append(Alert(alert_id=f"a{len(alerts) + 1}", type=t, severity=sev, line_id=line_id,
                            message_fr=msg, suggested_action=action, data=data))

    # 1) history base ("comme mardi dernier")
    hist = find_history_order(customer, ex.history_ref, call_date)
    if hist:
        for h in hist["lines"]:
            p = cat.by_sku.get(h["sku"])
            if not p:
                continue
            lines[p.sku] = OrderLine(
                line_id=f"L{next(ids)}", raw_mention=f"(historique {hist['date']})", sku=p.sku,
                product_label=p.label, quantity=h["qty"], sell_unit=p.sell_unit,
                confidence=0.95, match_score=100, source=LineSource.history,
            )
        alert(AlertType.HISTORY_USED, Severity.info,
              f"Reprise de la commande du {hist['date']} ({len(hist['lines'])} lignes).",
              order_date=hist["date"])

    # 2) voice mentions, in order
    for m in ex.mentions:
        hinted = cat.by_sku.get(m.sku_hint) if m.sku_hint else None
        res = cat.match(m.product_text)
        product = hinted or res.product
        score = 100.0 if hinted else res.score
        ambiguous = res.ambiguous and not hinted

        if m.action == "remove":
            if product and product.sku in lines:
                del lines[product.sku]
            continue

        if product is None:
            key = f"UNK:{m.product_text.lower()}"
            lid = f"L{next(ids)}"
            lines[key] = OrderLine(
                line_id=lid, raw_mention=m.raw, sku=None, product_label=m.product_text,
                spoken_quantity=m.quantity, spoken_unit=Unit(m.unit) if m.unit else None,
                confidence=0.2, match_score=round(res.score, 1), candidates=res.candidates,
            )
            alert(AlertType.UNKNOWN_SKU, Severity.block,
                  f"« {m.product_text} » introuvable au catalogue.", lid,
                  "Choisir un produit proche ou créer l'article", candidates=[c.model_dump() for c in res.candidates])
            continue

        qty, est = convert(m.quantity, m.unit, product)
        existing = lines.get(product.sku)
        if existing and existing.source == LineSource.history and m.increment and qty is not None:
            qty = (existing.quantity or 0) + qty
        elif existing and m.action == "add" and existing.source == LineSource.voice and qty is not None \
                and m.increment:
            qty = (existing.quantity or 0) + qty
        lid = existing.line_id if existing else f"L{next(ids)}"
        conf = stt_confidence * (score / 100) * (0.6 if ambiguous else 1) * (0.9 if est else 1) \
            * (0.8 if m.conditional else 1) * (1 if qty is not None else 0.4)
        lines[product.sku] = OrderLine(
            line_id=lid, raw_mention=m.raw, sku=product.sku, product_label=product.label,
            spoken_quantity=m.quantity, spoken_unit=Unit(m.unit) if m.unit else None,
            quantity=qty, sell_unit=product.sell_unit, quantity_is_estimate=est,
            conditional=m.conditional, confidence=round(min(conf, 1), 3), match_score=round(score, 1),
            candidates=res.candidates, source=LineSource.voice,
        )
        if ambiguous:
            alert(AlertType.AMBIGUOUS_SKU, Severity.block,
                  f"« {m.product_text} » : plusieurs produits possibles.", lid,
                  "Demander au client / choisir", candidates=[c.model_dump() for c in res.candidates[:3]])
        if qty is None and m.quantity is not None:
            alert(AlertType.UNIT_MISMATCH, Severity.block,
                  f"Unité « {m.unit} » non convertible pour {product.label} (vendu au {product.sell_unit.value}).", lid)
        if est:
            alert(AlertType.WEIGHT_ESTIMATE, Severity.info,
                  f"{m.quantity:g} pièce(s) de {product.label} ≈ {qty:g} kg (poids estimé, à confirmer à la pesée).", lid)
        if m.conditional:
            alert(AlertType.CONDITIONAL_LINE, Severity.warn,
                  f"Ligne conditionnelle : « {m.conditional} ».", lid, "Vérifier la qualité avant préparation")

    # 3) per-line checks: stock, substitution, anomalies, price, confidence
    for ln in lines.values():
        if not ln.sku:
            continue
        p = cat.by_sku[ln.sku]
        ln.unit_price_eur = p.price_eur
        if ln.quantity is not None:
            ln.line_total_eur = round(ln.quantity * p.price_eur, 2)
        if p.stock <= 0:
            ln.stock_status = StockStatus.out
            sub = next((cat.by_sku[s] for s in p.substitutes if s in cat.by_sku and cat.by_sku[s].stock > 0), None)
            if sub:
                ln.substitution = Substitution(sku=sub.sku, label=sub.label,
                                               reason=f"{p.label} en rupture ; {sub.label} disponible à {sub.price_eur:.2f} €")
            alert(AlertType.OUT_OF_STOCK, Severity.block, f"{p.label} en rupture.", ln.line_id,
                  f"Proposer {sub.label}" if sub else "Prévenir le client", substitute=sub.sku if sub else None)
        elif ln.quantity is not None and ln.quantity > p.stock:
            ln.stock_status = StockStatus.low
            alert(AlertType.LOW_STOCK, Severity.warn,
                  f"Stock {p.label} : {p.stock:g} {p.sell_unit.value} dispo pour {ln.quantity:g} demandés.", ln.line_id)
        else:
            ln.stock_status = StockStatus.ok
        u = usual_qty(customer, ln.sku)
        if u and ln.quantity and ln.source == LineSource.voice and not (ANOMALY_LOW <= ln.quantity / u <= ANOMALY_HIGH):
            alert(AlertType.QUANTITY_ANOMALY, Severity.warn,
                  f"{ln.product_label} : {ln.quantity:g} {p.sell_unit.value} vs {u:g} d'habitude (×{ln.quantity / u:.1f}).",
                  ln.line_id, "Faire confirmer la quantité", usual=u)
        if ln.confidence < REVIEW_THRESHOLD and ln.source == LineSource.voice:
            alert(AlertType.LOW_CONFIDENCE, Severity.warn,
                  f"Confiance faible sur {ln.product_label} ({ln.confidence:.0%}).", ln.line_id)

    for q in ex.price_questions:
        r = cat.match(q)
        if r.product:
            alert(AlertType.PRICE_REQUEST, Severity.info,
                  f"Le client demande le prix : {r.product.label} = {r.product.price_eur:.2f} €/{r.product.sell_unit.value}.",
                  None, "Répondre au client", sku=r.product.sku)

    # 4) upsell: frequent items missing (only for fresh orders, not "comme d'hab")
    if customer and not hist and lines:
        freq: dict[str, int] = {}
        for o in customer.get("orders", []):
            for h in o["lines"]:
                freq[h["sku"]] = freq.get(h["sku"], 0) + 1
        missing = [s for s, n in sorted(freq.items(), key=lambda x: -x[1]) if n >= 2 and s not in lines]
        for s in missing[:2]:
            p = cat.by_sku.get(s)
            if p and p.stock > 0:
                alert(AlertType.UPSELL, Severity.info, f"Commande habituellement {p.label} — le proposer ?",
                      None, "Proposer au client", sku=s, usual=usual_qty(customer, s))

    out = list(lines.values())
    gconf = min((l.confidence for l in out), default=0.0)
    blocking = any(a.severity == Severity.block for a in alerts)
    total = sum(l.line_total_eur or 0 for l in out)
    return OrderDraft(
        call_id=call_id, customer_id=customer.get("customer_id") if customer else None,
        customer_name=customer.get("name") if customer else None,
        status=OrderStatus.needs_review if (blocking or gconf < REVIEW_THRESHOLD) else OrderStatus.draft,
        delivery_date=_delivery(ex.delivery_hint, call_date),
        lines=out, alerts=alerts, global_confidence=round(gconf, 3),
        total_eur=round(total, 2), extractor=ex.extractor,
    )


def _delivery(hint: Optional[str], d: date) -> str:
    if hint in DAYS:
        delta = (DAYS.index(hint) - d.weekday()) % 7 or 7
        return (d + timedelta(days=delta)).isoformat()
    if hint and "apr" in hint:
        return (d + timedelta(days=2)).isoformat()
    return (d + timedelta(days=1)).isoformat()   # default: next-morning delivery
