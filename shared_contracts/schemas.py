"""
FROZEN DATA CONTRACTS — single source of truth between pods.

    Pod A (voice)  --TranscriptEvent-->  Pod B (agent)  --OrderDraft-->  Pod C (UI)
    Pod C (UI)     --OperatorAction--->  Pod B (agent)
    server         --DashboardEvent--->  Pod C (UI, over WebSocket /ws)

Change protocol (see CLAUDE.md §4): never edit this file inside a pod branch.
Write a proposal in docs/contract_proposals/, get Architect OK, bump CONTRACT_VERSION,
regenerate JSON schemas with `make schemas`, announce on the team channel.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.0.0"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ───────────────────────────── Enums ─────────────────────────────

class Unit(str, Enum):
    """Spoken or sell units. Keep French trade vocabulary."""
    kg = "kg"
    g = "g"
    piece = "piece"
    botte = "botte"
    barquette = "barquette"
    plateau = "plateau"
    colis = "colis"
    cagette = "cagette"
    caisse = "caisse"
    sac = "sac"
    filet = "filet"
    palette = "palette"
    litre = "litre"
    bidon = "bidon"


class Speaker(str, Enum):
    client = "client"
    agent = "agent"
    unknown = "unknown"


class LineAction(str, Enum):
    add = "add"          # new line, or "+N en plus" on an existing line
    set = "set"          # replace quantity (corrections, "plutôt 2")
    remove = "remove"    # "enlève l'huile"


class StockStatus(str, Enum):
    ok = "ok"
    low = "low"
    out = "out"
    unknown = "unknown"


class LineSource(str, Enum):
    voice = "voice"        # stated in this call
    history = "history"    # "comme mardi dernier"
    operator = "operator"  # added/edited by human in the UI


class AlertType(str, Enum):
    UNKNOWN_SKU = "UNKNOWN_SKU"
    AMBIGUOUS_SKU = "AMBIGUOUS_SKU"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    LOW_STOCK = "LOW_STOCK"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    WEIGHT_ESTIMATE = "WEIGHT_ESTIMATE"      # pieces of fish/meat converted to kg
    CONDITIONAL_LINE = "CONDITIONAL_LINE"    # "si elles sont belles"
    QUANTITY_ANOMALY = "QUANTITY_ANOMALY"    # far from customer's usual
    PRICE_REQUEST = "PRICE_REQUEST"          # "c'est combien le cabillaud ?"
    HISTORY_USED = "HISTORY_USED"            # "comme mardi dernier"
    UPSELL = "UPSELL"                        # usual item missing from order


class Severity(str, Enum):
    info = "info"
    warn = "warn"
    block = "block"   # order cannot be auto-injected until a human resolves it


class OrderStatus(str, Enum):
    listening = "listening"
    draft = "draft"
    needs_review = "needs_review"
    confirmed = "confirmed"
    injected = "injected"


# ─────────────────────── Pod A → Pod B ───────────────────────

class WordTiming(BaseModel):
    w: str
    start_ms: int
    end_ms: int
    conf: float = Field(ge=0, le=1)


class AudioMeta(BaseModel):
    source: Literal["mock", "file", "mic", "telephony"] = "mock"
    provider: str = "mock"                 # mock | openai | deepgram | ...
    sample_rate_hz: Optional[int] = None   # 8000 for PSTN
    duration_ms: Optional[int] = None
    stt_latency_ms: Optional[int] = None
    noise_tag: Optional[str] = None        # e.g. "chambre_froide", "rungis"


class TranscriptEvent(BaseModel):
    call_id: str
    seq: int = Field(ge=0, description="monotonic per call")
    ts: datetime = Field(default_factory=now_utc)
    speaker: Speaker = Speaker.client
    text: str
    is_final: bool = True                  # partials are for UI only; Pod B acts on finals
    confidence: float = Field(default=0.9, ge=0, le=1)
    lang: str = "fr"
    customer_id: Optional[str] = None      # resolved from caller ID if known
    caller_number: Optional[str] = None
    words: list[WordTiming] = Field(default_factory=list)
    audio: AudioMeta = Field(default_factory=AudioMeta)


# ─────────────────────── Pod B → Pod C ───────────────────────

class Candidate(BaseModel):
    sku: str
    label: str
    score: float = Field(ge=0, le=100)


class Substitution(BaseModel):
    sku: str
    label: str
    reason: str


class OrderLine(BaseModel):
    line_id: str
    raw_mention: str                       # exact span from transcript
    sku: Optional[str] = None              # None = unknown product
    product_label: str
    spoken_quantity: Optional[float] = None
    spoken_unit: Optional[Unit] = None
    quantity: Optional[float] = None       # in sell_unit (what the ERP needs)
    sell_unit: Optional[Unit] = None
    quantity_is_estimate: bool = False
    unit_price_eur: Optional[float] = None
    line_total_eur: Optional[float] = None
    conditional: Optional[str] = None      # "si elles sont belles"
    confidence: float = Field(ge=0, le=1)
    match_score: float = Field(default=0, ge=0, le=100)
    candidates: list[Candidate] = Field(default_factory=list)
    stock_status: StockStatus = StockStatus.unknown
    substitution: Optional[Substitution] = None
    source: LineSource = LineSource.voice
    operator_override: bool = False


class Alert(BaseModel):
    alert_id: str
    type: AlertType
    severity: Severity
    line_id: Optional[str] = None
    message_fr: str
    suggested_action: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class Latency(BaseModel):
    stt_ms: Optional[int] = None
    extract_ms: Optional[int] = None
    total_ms: Optional[int] = None


class OrderDraft(BaseModel):
    contract_version: str = CONTRACT_VERSION
    call_id: str
    version: int = 0                       # increments on every re-extraction / operator action
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    status: OrderStatus = OrderStatus.listening
    delivery_date: Optional[str] = None    # ISO date
    lines: list[OrderLine] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    global_confidence: float = Field(default=0, ge=0, le=1)
    total_eur: Optional[float] = None
    readback_fr: Optional[str] = None      # text for the confirmation read-back (TTS)
    extractor: Literal["llm", "rules"] = "rules"
    latency: Latency = Field(default_factory=Latency)
    updated_at: datetime = Field(default_factory=now_utc)


# ─────────────────────── Pod C → Pod B ───────────────────────

class OperatorAction(BaseModel):
    call_id: str
    action: Literal[
        "accept_line", "delete_line", "edit_line",
        "choose_candidate", "accept_substitution",
        "add_line", "confirm_order",
    ]
    line_id: Optional[str] = None
    sku: Optional[str] = None
    quantity: Optional[float] = None       # in sell unit
    operator: str = "operator"


# ─────────────────────── Server → UI (WebSocket) ───────────────────────

class DashboardEvent(BaseModel):
    type: Literal["transcript", "order", "status", "error"]
    call_id: str
    payload: dict[str, Any]
    ts: datetime = Field(default_factory=now_utc)


__all__ = [n for n in dir() if not n.startswith("_")]
