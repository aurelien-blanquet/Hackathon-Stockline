"""/market: « le marché du matin », a central buying agent negotiating with every supplier at the same time.

POST /market/rounds                 start a round → {id}
GET  /market/rounds/latest          the last round: {id, done, events} (a page opened mid-round catches up)
GET  /market/rounds/{id}/events     text/event-stream of MarketEvent: everything so far, then live until the end
"""

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from pydantic import Field

from app.market.events import MarketEvent
from app.market.round import ROUNDS, MarketRound, start_round
from app.schemas.base import WireModel

from .sse import sse_response

router = APIRouter(prefix="/market", tags=["market"])


class StartRound(WireModel):
    pace: float = Field(1.0, ge=0, le=3, description="1 = human-followable demo pace, 0 = as fast as possible")
    per_category: int = Field(2, ge=1, le=5, description="Products per category in the basket")


class RoundState(WireModel):
    id: str
    done: bool
    events: list[MarketEvent]


@router.post("/rounds", response_model=RoundState)
async def start(body: StartRound | None = None):
    body = body or StartRound()
    r = start_round(pace=body.pace, per_category=body.per_category)
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
