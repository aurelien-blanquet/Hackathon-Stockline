"""
Think while the caller speaks: the model's first step is started on the settled partial transcript, BEFORE the caller
releases the key. When the real turn then asks the model the same thing (same history, same words, same preloaded
facts), it gets that answer, already under way or finished, instead of starting from zero (~1 s saved, with the full
model, not a smaller one).

    speculate()   builds the same request the turn will build (history + the words so far + the read-only preload +
                  the sales stance), starts llm.stream(request), records its events
    SpecLLM       wraps the model client of the real turn: a request whose fingerprint matches a speculation replays
                  the recorded events then follows the live ones; otherwise the model is called as usual
    fingerprint   the request without what varies between two identical turns: tool-call ids, case and punctuation of
                  the caller's words

Never a write: the speculation only asks the model; tools run in the real turn (writes still wait for the final words).
A miss costs one model call, nothing else.
"""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field

from app.clients import LLMRequest
from app.schemas import ChatMessage

MAX_KEPT = 4  # speculations kept per process (each utterance replaces the previous ones)


def _norm_words(t: str) -> str:
    return " ".join(re.sub(r"[^\w']+", " ", (t or "").lower()).split())


def fingerprint(request: LLMRequest) -> str:
    def msg(m: ChatMessage) -> dict:
        return {
            "r": m.role,
            "c": _norm_words(m.content) if m.role == "user" else (m.content or ""),
            "t": [[c.name, json.dumps(c.arguments, sort_keys=True, default=str)] for c in m.tool_calls or []],
            "n": m.name if m.role == "tool" else None,
        }

    body = {"s": request.system, "m": [msg(m) for m in request.messages], "tools": sorted(getattr(t, "name", None) or t["name"] for t in request.tools or [])}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


@dataclass
class Speculation:
    key: str
    events: list = field(default_factory=list)
    done: bool = False
    failed: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


SPECS: dict[str, Speculation] = {}


async def _record(spec: Speculation, llm, request: LLMRequest) -> None:
    try:
        async for ev in llm.stream(request):
            spec.events.append(ev)
            spec.changed.set()
    except Exception:  # noqa: BLE001 — a failed speculation is simply not used
        spec.failed = True
    finally:
        spec.done = True
        spec.changed.set()


def start(llm, request: LLMRequest) -> Speculation:
    key = fingerprint(request)
    if key in SPECS and not SPECS[key].failed:
        return SPECS[key]
    spec = Speculation(key)
    spec.task = asyncio.create_task(_record(spec, llm, request))
    SPECS[key] = spec
    for old in list(SPECS)[:-MAX_KEPT]:
        stale = SPECS.pop(old)
        if stale.task and not stale.task.done():
            stale.task.cancel()
    return spec


class SpecLLM:
    """The real turn's model client: replays a matching speculation, else streams as usual."""

    def __init__(self, inner):
        self.inner = inner
        self.provider, self.model = inner.provider, inner.model
        self.hit = False

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def stream(self, request: LLMRequest):
        spec = SPECS.pop(fingerprint(request), None)
        if spec is None or spec.failed:
            async for ev in self.inner.stream(request):
                yield ev
            return
        self.hit = True
        print("[voice] speculation hit: the answer was prepared while the caller spoke", flush=True)
        i = 0
        while True:
            while i < len(spec.events):
                yield spec.events[i]
                i += 1
            if spec.done:
                if spec.failed and i == 0:  # nothing came: ask for real
                    async for ev in self.inner.stream(request):
                        yield ev
                return
            spec.changed.clear()
            if i < len(spec.events) or spec.done:
                continue
            await spec.changed.wait()
