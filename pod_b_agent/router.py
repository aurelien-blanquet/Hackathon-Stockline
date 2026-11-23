"""Pod B HTTP surface: /api/agent/*. Owned by Pod B."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.bus import bus
from shared_contracts.schemas import OperatorAction, OrderDraft, TranscriptEvent

from .catalog import load_catalog, load_customers
from .pipeline import CALLS, apply_operator, extract_order, inject_erp, on_transcript

router = APIRouter(prefix="/api/agent", tags=["pod_b_agent"])


async def handle_transcript(ev: TranscriptEvent) -> None:   # bus subscriber
    draft = await on_transcript(ev)
    if draft:
        await bus.publish("order", draft)


class ExtractRequest(BaseModel):
    text: str
    customer_id: Optional[str] = None
    call_date: Optional[date] = None
    mode: Optional[str] = None          # rules | llm


@router.post("/extract", response_model=OrderDraft)
async def extract(req: ExtractRequest) -> OrderDraft:
    """Stateless: text in, OrderDraft out. Used by eval and for debugging."""
    return await extract_order(req.text, "adhoc", req.customer_id, req.call_date, req.mode)


@router.post("/operator", response_model=OrderDraft)
async def operator(act: OperatorAction) -> OrderDraft:
    if act.call_id not in CALLS or CALLS[act.call_id].draft is None:
        raise HTTPException(404, "unknown call")
    d = apply_operator(act)
    await bus.publish("order", d)
    return d


@router.get("/catalog")
def catalog() -> list[dict]:
    return [{"sku": p.sku, "label": p.label, "sell_unit": p.sell_unit.value, "price_eur": p.price_eur,
             "stock": p.stock} for p in load_catalog().products]


@router.get("/customers")
def customers() -> list[dict]:
    return [{"customer_id": c["customer_id"], "name": c["name"], "phone": c.get("phone")}
            for c in load_customers().values()]


@router.get("/calls/{call_id}", response_model=OrderDraft)
def get_call(call_id: str) -> OrderDraft:
    st = CALLS.get(call_id)
    if not st or not st.draft:
        raise HTTPException(404, "unknown call")
    return st.draft
