"""What the trading floor receives: one MarketEvent per step of the round (streamed by GET /market/rounds/{id}/events).

type   round_started (needs, suppliers) · call_skipped · call_ringing · call_connected · line (speaker buyer|supplier,
       text) · offer (offers[], final) · intel (the buyer uses a competitor's price: fromCall → call) · call_waiting ·
       decision (allocations, uncovered, total, reference, savings) · call_ended (won, total) · po_created · summary · error
t      ms since the round started (the swimlane timeline: calls overlap)
call   supplier id = the call's id (None for round-level events)
"""

from typing import Any

from pydantic import Field

from app.schemas.base import WireModel


class MarketEvent(WireModel):
    type: str
    t: int
    call: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
