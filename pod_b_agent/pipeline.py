"""Pod B orchestration: per-call state, re-extraction on each final transcript chunk,
operator actions (human-in-the-loop), read-back text, ERP injection stub."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from shared_contracts.schemas import (
    LineSource, OperatorAction, OrderDraft, OrderLine, OrderStatus, Severity, StockStatus,
    TranscriptEvent, now_utc,
)

from .catalog import ROOT, load_catalog, load_customers
from .extractor_llm import extract_llm
from .extractor_rules import extract_rules
from .resolver import REVIEW_THRESHOLD, resolve

EXTRACTOR = os.getenv("EXTRACTOR", "rules")         # rules | llm
ERP_OUT = ROOT / "data" / "erp_orders.jsonl"


def customer_from_phone(number: Optional[str]) -> Optional[dict]:
    if not number:
        return None
    return next((c for c in load_customers().values() if c.get("phone") == number), None)


async def extract_order(text: str, call_id: str = "adhoc", customer_id: Optional[str] = None,
                        call_date: Optional[date] = None, mode: Optional[str] = None,
                        stt_confidence: float = 0.92) -> OrderDraft:
    t0 = time.perf_counter()
    customer = load_customers().get(customer_id) if customer_id else None
    mode = mode or EXTRACTOR
    ex = await extract_llm(text, customer) if mode == "llm" else extract_rules(text)
    draft = resolve(ex, call_id, customer, call_date or date.today(), stt_confidence=stt_confidence)
    draft.latency.extract_ms = int((time.perf_counter() - t0) * 1000)
    draft.readback_fr = readback_fr(draft)
    return draft


def readback_fr(d: OrderDraft) -> str:
    parts = []
    for l in d.lines:
        if not l.sku or l.quantity is None:
            continue
        su = l.sell_unit.value if l.sell_unit else "piece"
        approx = "environ " if l.quantity_is_estimate else ""
        q = f"{l.quantity:g}".replace(".", ",")
        if su == "piece":
            parts.append(f"{approx}{q} × {l.product_label}")
        else:
            unit = "kilo" if su == "kg" else su
            plural = l.quantity > 1 and not unit.endswith(("s", "x"))
            unit += ("x" if unit.endswith("eau") else "s") if plural else ""
            parts.append(f"{approx}{q} {unit} de {l.product_label}")
    if not parts:
        return "Je n'ai pas encore de produit dans la commande."
    s = "Je récapitule : " + ", ".join(parts) + "."
    outs = [l.product_label for l in d.lines if l.stock_status == StockStatus.out]
    if outs:
        s += " Attention, " + " et ".join(outs) + (" est" if len(outs) == 1 else " sont") + " en rupture."
    return s + " C'est bon pour vous ?"


@dataclass
class CallState:
    call_id: str
    customer_id: Optional[str] = None
    finals: list[str] = field(default_factory=list)
    stt_conf: list[float] = field(default_factory=list)
    stt_ms: Optional[int] = None
    draft: Optional[OrderDraft] = None
    version: int = 0
    locked: bool = False          # once an operator edits, stop overwriting their changes


CALLS: dict[str, CallState] = {}


async def on_transcript(ev: TranscriptEvent) -> Optional[OrderDraft]:
    """Called by the bus for every TranscriptEvent. Re-extracts on finals only."""
    st = CALLS.setdefault(ev.call_id, CallState(ev.call_id))
    if ev.customer_id:
        st.customer_id = ev.customer_id
    elif not st.customer_id and (c := customer_from_phone(ev.caller_number)):
        st.customer_id = c["customer_id"]
    if not ev.is_final or st.locked:
        return None
    st.finals.append(ev.text)
    st.stt_conf.append(ev.confidence)
    st.stt_ms = ev.audio.stt_latency_ms or st.stt_ms
    t0 = time.perf_counter()
    draft = await extract_order(" ".join(st.finals), ev.call_id, st.customer_id,
                                stt_confidence=min(st.stt_conf))
    st.version += 1
    draft.version = st.version
    draft.latency.stt_ms = st.stt_ms
    draft.latency.total_ms = int((time.perf_counter() - t0) * 1000) + (st.stt_ms or 0)
    st.draft = draft
    return draft


def apply_operator(act: OperatorAction) -> OrderDraft:
    st = CALLS[act.call_id]
    d = st.draft
    assert d is not None, "no draft for this call"
    st.locked = True
    cat = load_catalog()
    line = next((l for l in d.lines if l.line_id == act.line_id), None)

    def clear_alerts(line_id: str) -> None:
        d.alerts = [a for a in d.alerts if a.line_id != line_id]

    if act.action == "delete_line" and line:
        d.lines.remove(line); clear_alerts(line.line_id)
    elif act.action in ("choose_candidate", "accept_substitution", "edit_line") and line:
        sku = act.sku or (line.substitution.sku if line.substitution else line.sku)
        p = cat.by_sku[sku]
        if line.sku != sku and line.quantity is None and line.spoken_quantity is not None:
            line.quantity = line.spoken_quantity
        line.sku, line.product_label, line.sell_unit = p.sku, p.label, p.sell_unit
        if act.quantity is not None:
            line.quantity = act.quantity
        line.unit_price_eur = p.price_eur
        line.line_total_eur = round((line.quantity or 0) * p.price_eur, 2)
        line.stock_status = StockStatus.ok if p.stock > 0 else StockStatus.out
        line.substitution, line.operator_override, line.confidence = None, True, 1.0
        clear_alerts(line.line_id)
    elif act.action == "accept_line" and line:
        line.operator_override, line.confidence = True, 1.0
        clear_alerts(line.line_id)
    elif act.action == "add_line" and act.sku:
        p = cat.by_sku[act.sku]
        n = max([int(l.line_id[1:]) for l in d.lines] + [0]) + 1
        d.lines.append(OrderLine(line_id=f"L{n}", raw_mention="(ajout opérateur)", sku=p.sku,
                                 product_label=p.label, quantity=act.quantity or 1, sell_unit=p.sell_unit,
                                 unit_price_eur=p.price_eur, line_total_eur=round((act.quantity or 1) * p.price_eur, 2),
                                 confidence=1.0, match_score=100, source=LineSource.operator,
                                 operator_override=True, stock_status=StockStatus.ok))
        d.alerts = [a for a in d.alerts if not (a.type.value == "UPSELL" and a.data.get("sku") == act.sku)]
    elif act.action == "confirm_order":
        inject_erp(d)

    if d.status != OrderStatus.injected:
        blocking = any(a.severity == Severity.block for a in d.alerts)
        d.global_confidence = min((l.confidence for l in d.lines), default=0)
        d.status = OrderStatus.needs_review if blocking or d.global_confidence < REVIEW_THRESHOLD else OrderStatus.confirmed
    d.total_eur = round(sum(l.line_total_eur or 0 for l in d.lines), 2)
    d.readback_fr = readback_fr(d)
    st.version += 1
    d.version, d.updated_at = st.version, now_utc()
    return d


def inject_erp(d: OrderDraft) -> None:
    """ERP stub: append one JSON order per line to data/erp_orders.jsonl.
    Replace with Stockline's API / mock as soon as Titus tells us the format."""
    payload = {
        "order_ref": f"VOX-{d.call_id}", "customer_id": d.customer_id, "delivery_date": d.delivery_date,
        "lines": [{"sku": l.sku, "qty": l.quantity, "unit": l.sell_unit.value if l.sell_unit else None,
                   "comment": l.conditional} for l in d.lines if l.sku and l.quantity],
        "source": "voice_agent", "created_at": now_utc().isoformat(),
    }
    ERP_OUT.parent.mkdir(exist_ok=True)
    with ERP_OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    d.status = OrderStatus.injected
