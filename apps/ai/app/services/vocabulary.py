"""
Company vocabulary for speech-to-text: the names a generic model mishears — product names and the aliases people
actually say ("loup" for bar), client names — read from the ERP and sent to the STT as context terms
(Soniox `context.terms`, Deepgram `keyterm`). Cached a few minutes: a product added in the ERP is heard soon after.
"""

import asyncio
import time

from app.tools.erp import ErpClient

TTL_S = 300  # refresh every 5 min
RETRY_S = 30  # ERP down: try again sooner
MAX_TERMS = 500

_cache: tuple[float, list[str]] = (0.0, [])  # (expires at, terms)
_lock = asyncio.Lock()


# Words of the trade the caller says in almost every order (units, formats): boosted right after the products.
TRADE_TERMS = [
    "meule", "demi-meule", "meule entière", "barquette", "plateau", "carton", "seau", "brique", "sachet", "pièce",
    "kilos", "fermier", "laitier", "lait cru", "affiné", "AOP", "IGP", "comme d'habitude", "pastille verte",
    "pastille rouge",
]


async def company_terms(erp: ErpClient | None = None) -> list[str]:
    """What callers say, most useful first, since the STT keeps only the first terms (Deepgram: 50 keyterms;
    soniox.py MAX_TERMS_CHARS): product aliases ("reblo", "diots"), short product names ("Reblochon de Savoie AOP
    fermier", without the "(450 g)" format), trade words (units, formats), then client names. A phone order is
    mostly products and quantities; the caller says their own name once. [] when the ERP does not answer.
    Order: each product's main alias, product names, trade words, the other aliases, then clients."""
    global _cache
    async with _lock:
        expires, terms = _cache
        if time.monotonic() < expires:
            return terms
        erp = erp or ErpClient("voice_agent")
        try:
            products, clients = await asyncio.wait_for(
                asyncio.gather(erp.get("/api/products", {"limit": 500}), erp.get("/api/clients", {"limit": 500})), 3
            )
            aliases = [p.get("aliases") or [] for p in products]
            names = [a[0] for a in aliases if a]  # one main word per product first ("reblochon fermier", "diots"…)
            names += [short_name(p.get("name") or "") for p in products]
            names += TRADE_TERMS
            names += [x for a in aliases for x in a[1:]]  # the other nicknames ("reblo", "pastille verte"…)
            names += [c.get("name") for c in clients]
            terms = dedupe(names)[:MAX_TERMS]
            _cache = (time.monotonic() + TTL_S, terms)
        except Exception as e:  # ERP unreachable, other shape…: transcribe without vocabulary
            print(f"[ai] STT vocabulary unavailable ({type(e).__name__}: {e}), retry in {RETRY_S}s", flush=True)
            _cache = (time.monotonic() + RETRY_S, terms)
        return _cache[1]


def short_name(name: str) -> str:
    """'Reblochon de Savoie AOP fermier (450 g)' → 'Reblochon de Savoie AOP fermier': the format is not said."""
    return name.split(" (")[0].strip()


def dedupe(names: list) -> list[str]:
    seen, out = set(), []
    for n in names:
        n = " ".join(str(n or "").replace(",", " ").split())  # the hint is a comma-separated list
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


async def stt_hint(stt_name: str, hint: str | None) -> str | None:
    """The hint sent to the STT: the caller's own hint first, then the company vocabulary.
    The mock STT returns its hint as the transcript, so it gets the caller's hint untouched."""
    if stt_name == "mock":
        return hint
    terms = await company_terms()
    return ", ".join([*([hint] if hint else []), *terms]) or None


def reset_cache() -> None:
    global _cache
    _cache = (0.0, [])
