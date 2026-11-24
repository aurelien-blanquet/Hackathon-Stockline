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


def _msg(m: ChatMessage) -> dict:
    return {
        "r": m.role,
        "c": _norm_words(m.content) if m.role == "user" else (m.content or ""),
        "t": [[c.name, json.dumps(c.arguments, sort_keys=True, default=str)] for c in m.tool_calls or []],
        "n": m.name if m.role == "tool" else None,
    }


def parts(request: LLMRequest) -> list[str]:
    """One short hash per part (system, tools, each message): where two requests differ."""
    h = lambda x: hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:8]  # noqa: E731
    return [h(request.system), h(sorted(getattr(t, "name", None) or t["name"] for t in request.tools or []))] + [h(_msg(m)) for m in request.messages]


def why_miss(request: LLMRequest) -> str:
    """The closest speculation, and the first part that differs (for the logs)."""
    mine = parts(request)
    best = None
    for spec in SPECS.values():
        same = next((i for i, (a, b) in enumerate(zip(mine, spec.parts)) if a != b), min(len(mine), len(spec.parts)))
        if best is None or same > best[0]:
            best = (same, spec)
    if best is None:
        return "aucune préparation en cours (pas de transcription partielle reçue, ou phrase trop courte)"
    i, spec = best
    names = ["prompt système", "outils"] + [f"message {k} ({m.role}{'/' + m.name if m.name else ''})" for k, m in enumerate(request.messages)]
    return f"diffère à partir de : {names[i] if i < len(names) else 'longueur'} ({len(mine)} parts vs {len(spec.parts)})"


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
    parts: list[str] = field(default_factory=list)  # per-message fingerprints (diagnosis of a miss)


SPECS: dict[str, Speculation] = {}
# A speculation being BUILT (preload, stance) for these words: the real turn waits for it instead of asking twice.
PENDING: dict[str, asyncio.Event] = {}
PENDING_WAIT_S = 0.8


def building(words: str) -> asyncio.Event:
    ev = asyncio.Event()
    PENDING[_norm_words(words)] = ev
    for old in list(PENDING)[:-MAX_KEPT]:
        PENDING.pop(old).set()
    return ev


def _last_user(request: LLMRequest) -> str:
    return next((_norm_words(m.content) for m in reversed(request.messages) if m.role == "user"), "")


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


def drop(spec: Speculation | None) -> None:
    """A speculation on words the caller has since added to: stopped (no more tokens paid), forgotten."""
    if spec is None:
        return
    if spec.task and not spec.task.done():
        spec.task.cancel()
    if SPECS.get(spec.key) is spec:
        SPECS.pop(spec.key, None)


def start(llm, request: LLMRequest) -> Speculation:
    key = fingerprint(request)
    if key in SPECS and not SPECS[key].failed:
        return SPECS[key]
    spec = Speculation(key, parts=parts(request))
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
        self.miss: str | None = None

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def stream(self, request: LLMRequest):
        key = fingerprint(request)
        if key not in SPECS and (ev := PENDING.get(_last_user(request))) and not ev.is_set():
            try:  # the same words are being prepared right now: wait for it rather than asking the model twice
                await asyncio.wait_for(ev.wait(), PENDING_WAIT_S)
            except TimeoutError:
                pass
        spec = SPECS.pop(key, None)
        if spec is None or spec.failed:
            if not self.hit and self.miss is None:  # first model step only
                self.miss = why_miss(request)
                print(f"[voice] speculation miss: {self.miss}", flush=True)
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
