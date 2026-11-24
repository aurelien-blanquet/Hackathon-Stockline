"""
Fast paths for the phone: answer with ONE model call, or none.

A model call costs ~0.65 s to the first token (Claude Haiku, measured with the team key; the prompt size does not
matter once cached). A turn that needs a tool costs two calls in a row. So, in code, before the model:

  fast_confirm()  « oui c'est bon » right after an order recap → confirm_order in code + a templated reply, NO model
                  call. Same guard as the model path (agent/guardrails.py may_confirm), and only for a clean draft (no
                  ERP warning, client not blocked): anything else goes to the model.
  preload()       the caller and the products named in the sentence are looked up in code (local ERP, ~0.1 s) and
                  added to the turn as if the model had called identify_caller / find_product: the model answers in
                  ONE call instead of two. Strict: a client is injected only if its name was really said (a colleague
                  « Julien au dépôt » is not the client whose contact is called Julien).

Both return what to append to the conversation (assistant tool calls + tool results [+ reply]) and never raise:
on any doubt or error they return nothing and the normal agent runs.
"""

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass

from app.agent.guardrails import may_confirm
from app.agent.speak_fr import say_date
from app.schemas import ChatMessage, ToolCall
from app.tools import TOOLS, ErpClient, ToolContext
from app.tools.voice import _norm, short_name

ORDER_TOOLS = ("create_draft_order", "add_order_line", "update_order_line", "remove_order_line", "update_order", "get_order")
MAX_CONFIRM_WORDS = 8  # « ouais vas-y c'est bon » yes; a long sentence probably says more than yes: the model reads it
STOP = {"le", "la", "les", "l", "de", "du", "des", "d", "chez", "au", "aux", "et", "a", "en", "sur", "the"}
INTRO = re.compile(r"\b(?:c'est|c est|ici|de la part de|je suis|moi c'est|je m'appelle)\s+(.+?)(?=[.!?,;:]|$)", re.I)


@dataclass
class Injected:
    """What a fast path adds to the turn: messages for the history, events for the UI, and maybe the final reply."""

    messages: list[ChatMessage]
    calls: list[tuple[ToolCall, object, int]]  # (call, result, ms) for the UI
    reply: str | None = None


def _call(name: str, arguments: dict) -> ToolCall:
    return ToolCall(id=f"fast_{uuid.uuid4().hex[:12]}", name=name, arguments=arguments)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _results(history: list[ChatMessage]):
    """(tool name, parsed result) of every tool message, oldest first."""
    for m in history:
        if m.role == "tool" and m.name:
            try:
                yield m.name, json.loads(m.content)
            except (ValueError, TypeError):
                continue


# ── « oui c'est bon » → confirm in code ──────────────────────────────────────────────────────────────────────────


def pending_draft(history: list[ChatMessage]) -> dict | None:
    """The draft order the conversation is about: the latest order result, if it is still a draft."""
    latest = None
    for name, r in _results(history):
        if name in (*ORDER_TOOLS, "confirm_order", "cancel_order") and isinstance(r, dict) and r.get("id"):
            latest = r
    return latest if latest and latest.get("status") == "draft" else None


def caller_blocked(history: list[ChatMessage]) -> bool:
    return any(name == "identify_caller" and isinstance(r, dict) and r.get("blocked") for name, r in _results(history))


async def fast_confirm(working: list[ChatMessage], erp: ErpClient, today: str | None) -> Injected | None:
    heard = working[-1].content
    if len(heard.split()) > MAX_CONFIRM_WORDS or not may_confirm(working, "voice"):
        return None
    draft = pending_draft(working[:-1])
    if not draft or draft.get("warnings") or not draft.get("lines") or caller_blocked(working):
        return None
    call = _call("confirm_order", {"orderId": draft["id"]})
    t0 = time.perf_counter()
    try:
        result = await TOOLS["confirm_order"].run(call.arguments, ToolContext(erp=erp, actor="voice_agent"))
    except Exception as e:
        print(f"[fast] confirm_order failed ({e}): the model handles the turn", flush=True)
        return None
    ms = int((time.perf_counter() - t0) * 1000)
    when = f", livraison {say_date(result['deliveryDate'], today)}" if result.get("deliveryDate") else ""
    reply = f"Parfait, c'est validé{when}."
    if warnings := [w.get("message") for w in result.get("warnings") or [] if w.get("message")]:
        reply += f" Attention : {' ; '.join(warnings)}."
    reply += " Merci, bonne journée !"
    messages = [
        ChatMessage(role="assistant", content="", tool_calls=[call]),
        ChatMessage(role="tool", tool_call_id=call.id, name=call.name, content=_json(result)),
        ChatMessage(role="assistant", content=reply),
    ]
    return Injected(messages=messages, calls=[(call, result, ms)], reply=reply)


# ── preload the caller and the products named ────────────────────────────────────────────────────────────────────


def _words(text: str) -> list[str]:
    """Normalised words, crude singular (« reblochons laitiers » → « reblochon laitier »)."""
    out = []
    for w in re.split(r"[^a-z0-9]+", _norm(text).replace("'", " ")):
        if w:
            out.append(w[:-1] if len(w) > 3 and w[-1] in "sx" else w)
    return out


_index: tuple[float, list[tuple[tuple[str, ...], str]]] = (0.0, [])  # (expires, [(words of a phrase, phrase)])


async def product_index(erp: ErpClient) -> list[tuple[tuple[str, ...], str]]:
    """Every alias and short name of the catalogue, as word tuples, longest first. Cached 5 minutes."""
    global _index
    if time.monotonic() < _index[0]:
        return _index[1]
    products = await erp.get("/api/products", {"limit": 500})
    phrases = {p for prod in products for p in [*(prod.get("aliases") or []), short_name(prod.get("name") or "")] if p}
    index = sorted(((tuple(_words(p)), p) for p in phrases if _words(p)), key=lambda x: -len(x[0]))
    _index = (time.monotonic() + 300, index)
    return index


def products_said(text: str, index: list[tuple[tuple[str, ...], str]], limit: int = 4) -> list[str]:
    """The catalogue phrases said in `text`, longest match first, no overlap: « vingt reblochons laitiers et de la
    tomme » → ["reblochon laitier", "tomme"]."""
    words = _words(text)
    used = [False] * len(words)
    found: list[tuple[int, str]] = []
    for phrase_words, phrase in index:
        n = len(phrase_words)
        for i in range(len(words) - n + 1):
            if tuple(words[i : i + n]) == phrase_words and not any(used[i : i + n]):
                used[i : i + n] = [True] * n
                found.append((i, phrase))
                break
    return [p for _, p in sorted(found)][:limit]


def known_client(history: list[ChatMessage]) -> str | None:
    """The client already identified in this conversation (identify_caller result or a tool call's clientId)."""
    client = None
    for m in history:
        if m.role == "assistant" and m.tool_calls:
            for c in m.tool_calls:
                if isinstance(c.arguments, dict) and isinstance(c.arguments.get("clientId"), str):
                    client = c.arguments["clientId"]
        if m.role == "tool" and m.name == "identify_caller":
            try:
                r = json.loads(m.content)
            except ValueError:
                continue
            if r.get("found"):
                client = r["client"]["id"]
    return client


def name_was_said(card: dict, text: str) -> bool:
    """Most of the client's name is in the sentence (all of it, or half of it + a contact's first name)."""
    said = set(_words(text))
    name = [w for w in _words(card["client"]["name"]) if w not in STOP]
    if not name:
        return False
    share = sum(w in said for w in name) / len(name)
    first_names = {_words(c["name"])[0] for c in card["client"].get("contacts") or [] if _words(c.get("name") or "")}
    return share == 1 or (share >= 0.5 and bool(first_names & said))


def who_segments(text: str) -> list[str]:
    """Where the caller's name probably is: after « c'est / ici / de la part de », else the first clause."""
    out = [m.group(1).strip() for m in INTRO.finditer(text)]
    first = re.split(r"[.!?]", text, maxsplit=1)[0].strip()
    if first and first not in out and len(first.split()) <= 8:
        out.append(first)
    return out


async def preload(working: list[ChatMessage], erp: ErpClient) -> Injected | None:
    heard = working[-1].content
    ctx = ToolContext(erp=erp, actor="voice_agent")
    try:
        said = products_said(heard, await product_index(erp))
        client_id = known_client(working[:-1])
        t0 = time.perf_counter()
        if client_id is None:
            for who in who_segments(heard):
                args = {"who": who, **({"products": [{"query": p} for p in said]} if said else {})}
                card = await TOOLS["identify_caller"].run(args, ctx)
                if card.get("found") and name_was_said(card, heard):
                    call = _call("identify_caller", args)
                    return _as_injected([(call, card, int((time.perf_counter() - t0) * 1000))])
        if not said:
            return None
        calls = [_call("find_product", {"query": p, **({"clientId": client_id} if client_id else {})}) for p in said]
        results = await asyncio.gather(*(TOOLS["find_product"].run(c.arguments, ctx) for c in calls))
        ms = int((time.perf_counter() - t0) * 1000)
        return _as_injected([(c, r, ms) for c, r in zip(calls, results, strict=True)])
    except Exception as e:
        print(f"[fast] preload skipped ({type(e).__name__}: {e})", flush=True)
        return None


def _as_injected(calls: list[tuple[ToolCall, object, int]]) -> Injected:
    messages = [ChatMessage(role="assistant", content="", tool_calls=[c for c, _, _ in calls])]
    messages += [ChatMessage(role="tool", tool_call_id=c.id, name=c.name, content=_json(r)) for c, r, _ in calls]
    return Injected(messages=messages, calls=calls)
