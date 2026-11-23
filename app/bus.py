"""In-process async pub/sub + WebSocket fan-out. Owned by the Architect.

Topics: "transcript" (TranscriptEvent), "order" (OrderDraft).
Every publish is also broadcast to connected dashboards as a DashboardEvent.
Swap for Redis pub/sub only if we ever need multiple processes (we won't in 22h).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable

from fastapi import WebSocket
from pydantic import BaseModel

from shared_contracts.schemas import DashboardEvent

log = logging.getLogger("bus")
Handler = Callable[[BaseModel], Awaitable[None]]


class Bus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._sockets: set[WebSocket] = set()

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def publish(self, topic: str, msg: BaseModel) -> None:
        await self.broadcast(DashboardEvent(type=topic, call_id=getattr(msg, "call_id", "?"),
                                            payload=msg.model_dump(mode="json")))
        for h in self._subs[topic]:
            asyncio.create_task(self._safe(h, msg))

    async def _safe(self, h: Handler, msg: BaseModel) -> None:
        try:
            await h(msg)
        except Exception:  # noqa: BLE001
            log.exception("handler %s failed", h)

    async def broadcast(self, ev: DashboardEvent) -> None:
        data = ev.model_dump_json()
        for ws in list(self._sockets):
            try:
                await ws.send_text(data)
            except Exception:  # noqa: BLE001
                self._sockets.discard(ws)

    def add_socket(self, ws: WebSocket) -> None:
        self._sockets.add(ws)

    def remove_socket(self, ws: WebSocket) -> None:
        self._sockets.discard(ws)


bus = Bus()
