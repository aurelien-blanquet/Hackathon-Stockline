"""/market: « le marché du matin », a central buying agent negotiating with every supplier at the same time.

POST /market/rounds                 start a round → {id}
GET  /market/rounds/latest          the last round: {id, done, events} (a page opened mid-round catches up)
GET  /market/rounds/{id}/events     text/event-stream of MarketEvent: everything so far, then live until the end
GET  /market/memory                 what the buyer learned: per supplier, the mean price drop each lever obtained
POST /market/memory/reset           forget it (a demo shows the learning from zero)
GET  /market/schedule               the daily replenishment: time (MORNING_MARKET_AT), last run, next run
GET  /market/pools                  group purchases (market/pool.py): the provisional orders open to newcomers, the last improvements
"""

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from pydantic import Field

from app.market import levers
from app.market.events import MarketEvent
from app.market.round import ROUNDS, MarketRound, start_round
from app.schemas.base import WireModel
from app.tools import ErpClient

from .sse import sse_response

router = APIRouter(prefix="/market", tags=["market"])


class StartRound(WireModel):
    pace: float = Field(1.0, ge=0, le=3, description="1 = human-followable demo pace, 0 = as fast as possible")
    per_category: int = Field(2, ge=1, le=5, description="Products per category in the basket")
    mode: str = Field("christmas", description="christmas: Christmas week (the page's demo) · daily: the morning replenishment (every product ≥ an average of its sales)")


class RoundState(WireModel):
    id: str
    done: bool
    events: list[MarketEvent]


@router.post("/rounds", response_model=RoundState)
async def start(body: StartRound | None = None):
    body = body or StartRound()
    if body.mode == "daily":
        from app.market.schedule import run_now

        r = run_now("manuel", pace=body.pace)
    else:
        r = start_round(pace=body.pace, per_category=body.per_category, mode="christmas")
    return RoundState(id=r.id, done=r.done, events=list(r.events))


@router.get("/rounds/latest", response_model=RoundState)
async def latest():
    if not ROUNDS:
        raise HTTPException(404, "Aucun marché lancé")
    r = list(ROUNDS.values())[-1]
    return RoundState(id=r.id, done=r.done, events=list(r.events))


async def replay(r: MarketRound) -> AsyncIterator[MarketEvent]:
    i = 0
    while True:
        async with r.updated:
            await r.updated.wait_for(lambda: len(r.events) > i or r.done)
            batch, finished = r.events[i:], r.done and len(r.events) <= i + len(r.events[i:])
        for ev in batch:
            yield ev
        i += len(batch)
        if finished and i >= len(r.events):
            return


@router.get("/rounds/{round_id}/events")
async def events(round_id: str):
    r = ROUNDS.get(round_id)
    if not r:
        raise HTTPException(404, "Marché introuvable")
    return sse_response(replay(r))


class LeverStatOut(WireModel):
    tries: int
    mean_drop_pct: float


class LearnedSupplier(WireModel):
    supplier_id: str
    name: str
    best: str | None = None
    best_label: str = ""
    levers: dict[str, LeverStatOut]


class LeverMemoryOut(WireModel):
    rounds: int
    suppliers: list[LearnedSupplier]


@router.get("/memory", response_model=LeverMemoryOut)
async def memory():
    try:
        names = {s["id"]: s["name"] for s in await ErpClient("voice_agent", "Agent achats").get("/api/suppliers", {"limit": 50})}
    except Exception:  # the ERP is down: ids instead of names
        names = {}
    return LeverMemoryOut(rounds=levers.MEMORY.rounds, suppliers=levers.MEMORY.summary(names))


@router.post("/memory/reset", response_model=LeverMemoryOut)
async def reset_memory():
    levers.MEMORY.reset()
    return LeverMemoryOut(rounds=0, suppliers=[])


@router.get("/pools")
async def pools() -> dict:
    from app.market import pool

    return pool.snapshot()


@router.get("/schedule")
async def schedule() -> dict:
    """The daily « Marché du matin » (market/schedule.py): its time, the last and next runs."""
    from app.market.schedule import STATE

    return STATE
