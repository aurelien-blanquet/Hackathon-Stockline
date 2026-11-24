"""
The « Marché du matin » runs by itself every morning: the agent buyer replenishes every product to AT LEAST an
average of its sales (backend purchasing.replenishment_needs: avg/day over REPLENISH_DAYS × REPLENISH_COVER_DAYS −
(available + incoming)), calling all the producers at once with the usual negotiation (learned levers included) and
writing the purchase orders as DRAFTS: a recommendation. Nothing is sent to a producer before the owner approves it
on the Marché du matin page (ERP POST /api/purchase-orders/{id}/send, logged under the owner's name); refusing cancels
the draft. Opening the page also makes sure today's recommendation exists (ensure_today).

    MORNING_MARKET_AT=06:00   local time of the daily run ("" = never by itself; the page button still works)
    MORNING_CATCHUP=1         the service starts after that time and today's run is not done → run it now

Once per day: a run is « done today » if this process ran it, or if the ERP already holds a purchase order noted
« Marché du matin, réassort du <date> » (a restart does not buy twice). A new run replaces the previous run's UNSENT
replenishment drafts (their need is recomputed from today's stock), never an order already sent to a producer.
"""

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any

from app.config import env
from app.tools import ErpClient

MORNING_MARKET_AT = env("MORNING_MARKET_AT", "06:00").strip()
MORNING_CATCHUP = env("MORNING_CATCHUP", "1").lower() not in ("0", "false", "off", "no")
MORNING_PACE = float(env("MORNING_PACE", "0"))  # 0: as fast as possible (nobody watches at 6 a.m.); the page replays it

STATE: dict[str, Any] = {"at": MORNING_MARKET_AT or None, "lastRun": None, "lastRoundId": None, "nextRun": None, "lastError": None}


def _now() -> datetime:
    return datetime.now()  # noqa: DTZ005 — the shop's wall clock: « 6 h du matin » is local time


def _at() -> time | None:
    try:
        h, m = MORNING_MARKET_AT.split(":")
        return time(int(h), int(m))
    except ValueError:
        return None


async def done_today(erp: ErpClient, day: date | None = None) -> bool:
    day = day or _now().date()
    if STATE["lastRun"] and STATE["lastRun"][:10] == day.isoformat():
        return True
    from .round import MARKET_NOTE

    try:
        pos = await erp.get("/api/purchase-orders", {"sort": "createdAt", "order": "desc", "limit": 100})  # newest first
    except Exception:  # noqa: BLE001 — the ERP is not up yet: the loop tries again at the next run
        return False
    return any(str(po.get("note") or "").startswith(f"{MARKET_NOTE}, réassort du {day.isoformat()}") for po in pos)


_ENSURE = asyncio.Lock()


async def ensure_today(trigger: str = "à l'ouverture de la page") -> dict:
    """The owner opens the Marché du matin page: today's recommendation must be there. Runs the replenishment if
    nothing ran today (schedule off, service started late with MORNING_CATCHUP=0, first launch) and none is running."""
    from .round import ROUNDS

    async with _ENSURE:  # two tabs opened at once: one round
        running = next((r for r in ROUNDS.values() if r.mode == "daily" and not r.done), None)
        if running:
            return {"started": False, "roundId": running.id}
        if await done_today(ErpClient("voice_agent", "Agent achats")):
            return {"started": False, "roundId": STATE["lastRoundId"]}
        return {"started": True, "roundId": run_now(trigger).id}


def run_now(trigger: str = "manuel", pace: float | None = None):
    """Start a replenishment round now (the page button, or the daily schedule)."""
    from .round import start_round

    r = start_round(mode="daily", pace=MORNING_PACE if pace is None else pace, trigger=trigger)
    STATE["lastRun"], STATE["lastRoundId"] = _now().isoformat(timespec="seconds"), r.id
    return r


async def daily_loop() -> None:
    """Started with the service (main.lifespan). Sleeps until MORNING_MARKET_AT, runs once, again tomorrow."""
    at = _at()
    if at is None:
        print("[morning] daily market off (MORNING_MARKET_AT empty)", flush=True)
        return
    erp = ErpClient("voice_agent", "Agent achats")
    await asyncio.sleep(5)  # let the ERP come up
    label = f"automatique, chaque matin à {MORNING_MARKET_AT}"
    if MORNING_CATCHUP and _now().time() >= at and not await done_today(erp):
        run_now(f"{label} (rattrapage au démarrage)")
    while True:
        now = _now()
        nxt = datetime.combine(now.date() + timedelta(days=1 if now.time() >= at else 0), at)
        STATE["nextRun"] = nxt.isoformat(timespec="minutes")
        await asyncio.sleep(max(1.0, (nxt - _now()).total_seconds()))
        try:
            if not await done_today(erp):
                run_now(label)
        except Exception as e:  # noqa: BLE001 — tomorrow will try again; said on GET /market/schedule
            STATE["lastError"] = str(e)
            print(f"[morning] daily market failed: {e}", flush=True)
