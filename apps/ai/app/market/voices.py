"""
What the agents SAY on the market calls. The numbers come from strategy.py; a model only phrases them in the speaker's
own voice (the supplier sheet: how they talk, their tics). Guard: every number it was given must appear verbatim in
its sentence, else the template is used. Mock provider, timeout or error → template: the market runs without keys.
"""

import asyncio
import random
import re
import time
from dataclasses import dataclass, field

from app.clients import LLMRequest, LLMText, LLMUsage, get_llm_client
from app.clients.anthropic import AnthropicLLM
from app.config import env, settings
from app.schemas import ChatMessage

TIMEOUT_S = 6.0
UNIT_WORDS = {"kg": "kg", "piece": "pièces", "box": "cartons", "liter": "L", "dozen": "douzaines"}

_llm = None


def market_llm():
    """A fast model for the 20–40 short lines of a round (MARKET_LLM_MODEL, default Claude Haiku 5.5 with Anthropic)."""
    global _llm
    if _llm is None:
        base = get_llm_client()
        if base.provider == "anthropic":
            _llm = AnthropicLLM(env("MARKET_LLM_MODEL", "claude-haiku-5-5"), settings.llm.api_key, getattr(base, "base_url", "https://api.anthropic.com"), effort="low")  # fmt: skip
        else:
            _llm = base
    return _llm


def eur(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") + " €"


def qty(x: float, unit: str) -> str:
    n = f"{x:,.0f}" if float(x).is_integer() or x >= 100 else f"{x:,.1f}"
    return f"{n.replace(',', ' ').replace('.', ',')} {UNIT_WORDS.get(unit, unit)}"


def short(name: str) -> str:
    """'Raclette de Savoie IGP au lait cru (meule entière 6 kg)' → 'Raclette de Savoie IGP au lait cru'."""
    return name.split(" (")[0].strip()


# Gender / number of the products' first word (the catalogue's words), for « la raclette », « le reblochon », « les œufs ».
GENDER = {"raclette": "f", "crème": "f", "tomme": "f", "pomme": "f", "mondeuse": "f", "fondue": "f", "charcuterie": "f",
          "reblochon": "m", "plateau": "m", "jus": "m", "beaufort": "m", "vin": "m", "jambon": "m", "beurre": "m",
          "lait": "m", "saucisson": "m", "petit": "m", "mélange": "m", "persillé": "m", "sérac": "m", "chevrotin": "m",
          "lardons": "p", "œufs": "p", "diots": "p", "crozets": "p", "oignons": "p", "cornichons": "p"}  # fmt: skip
VOWEL = tuple("aeiouyéèêàâîôûœh")


def spoken(name: str) -> str:
    """Product name as said in a sentence: short, first letter lower-case only (« raclette de Savoie IGP… »)."""
    n = short(name)
    return n[:1].lower() + n[1:]


def the(name: str) -> str:
    """« la raclette de Savoie… », « le reblochon… », « les œufs… », « l'abondance… »."""
    n = spoken(name)
    g = GENDER.get(n.split()[0].lower(), "m")
    return f"les {n}" if g == "p" else f"l'{n}" if n.lower().startswith(VOWEL) else f"{'la' if g == 'f' else 'le'} {n}"


def of(name: str) -> str:
    """« de raclette… », « d'œufs… » (after a quantity)."""
    n = spoken(name)
    return f"d'{n}" if n.lower().startswith(VOWEL) else f"de {n}"


SYSTEM = """Tu joues {who} au téléphone, pour un jeu de rôle réaliste entre un fournisseur savoyard et l'agent achats de la Crèmerie des Aravis (grossiste en fromages de Savoie).
Ta façon de parler : {persona}
Règles : 1 ou 2 phrases orales, naturelles, dans ton style (tutoiement si c'est ton habitude). Pas de liste, pas de markdown.
Les chiffres qu'on te donne doivent apparaître EXACTEMENT comme écrits (même format, même espace). N'invente aucun autre chiffre."""


def _ok(text: str, numbers: list[str]) -> bool:
    flat = re.sub(r"\s+", " ", text.replace(" ", " ").replace("\xa0", " "))
    return bool(text.strip()) and all(n in flat for n in numbers)


# ── metrics and cache ──


@dataclass
class VoiceStats:
    """What the narration cost: model calls, cache hits, templates used instead of a call, fallbacks, latency, tokens."""

    llm_calls: int = 0
    cache_hits: int = 0
    templates: int = 0  # greetings / thanks: written from the supplier sheet, no model call
    fallbacks: int = 0  # the model was asked but its line was refused (missing number, « non » for a yes) or late
    input_tokens: int = 0
    output_tokens: int = 0
    latencies_ms: list[int] = field(default_factory=list)

    def snapshot(self) -> dict:
        lat = sorted(self.latencies_ms)
        return {"llmCalls": self.llm_calls, "cacheHits": self.cache_hits, "templates": self.templates, "fallbacks": self.fallbacks,
                "inputTokens": self.input_tokens, "outputTokens": self.output_tokens,
                "medianLatencyMs": lat[len(lat) // 2] if lat else None, "maxLatencyMs": lat[-1] if lat else None}  # fmt: skip


STATS = VoiceStats()
_cache: dict[tuple, str] = {}  # (who, intent, numbers) → accepted line: a relaunched round says it again for free
CACHE_MAX = 1000


def reset_stats() -> None:
    global STATS
    STATS = VoiceStats()


# ── lines that need no model: greetings and thanks from the supplier sheet ──

TIC = re.compile(r"«\s*([^»]{8,140}?)\s*»")


def tics(persona: str) -> list[str]:
    """The supplier's catchphrases from its sheet (« Tics : « … » · « … » »)."""
    return [t.strip() for t in TIC.findall(persona or "")]


def tutoie(persona: str) -> bool:
    return bool(re.search(r"\btutoie\b", persona or "", re.IGNORECASE))


def greeting(first: str, company: str, persona: str, rng: random.Random) -> str:
    """« Gilbert, Fruitière du Val des Aravis, bonjour ! » — sometimes with one of their own tics."""
    STATS.templates += 1
    hello = rng.choice(["Allô, {f} à l'appareil, {c}, bonjour !", "{c}, {f}, bonjour !", "Oui allô, {f}, de chez {c}, je vous écoute."])
    if tutoie(persona):
        hello = rng.choice(["Allô, {f} de chez {c}, salut !", "{f}, {c}, je t'écoute !"])
    line = hello.format(f=first, c=company)
    own = [t for t in tics(persona) if not any(ch.isdigit() for ch in t)]  # a tic with a number could contradict the offer
    if own and rng.random() < 0.5:
        line += f" {own[0]}"
    return line


def thanks(first: str, persona: str, won: bool, rng: random.Random) -> str:
    STATS.templates += 1
    tu = tutoie(persona)
    if won:
        return rng.choice(["Parfait, merci ! Je prépare ça, bonnes fêtes.", "Top, merci pour la commande, on s'occupe de tout."] if tu
                          else ["Très bien, merci à vous. Je prépare ça.", "Parfait, c'est noté, merci et bonnes fêtes."])  # fmt: skip
    return rng.choice(["Dommage ! Rappelle-moi si tu manques de quelque chose.", "Pas de souci, la prochaine fois !"] if tu
                      else ["Entendu, une prochaine fois peut-être.", "Pas de souci, rappelez-moi si besoin."])  # fmt: skip


# A line that must say « yes » cannot sound like « no »: the code decided, the voice follows.
REFUSAL = re.compile(r"\b(non|peux pas|pas possible|impossible|refuse)\b", re.IGNORECASE)


async def phrase(who: str, persona: str, intent: str, numbers: list[str], fallback: str, forbid: re.Pattern | None = None) -> str:
    """The line `who` says to do `intent`, with these exact numbers. The template on any doubt (missing number,
    or a `forbid` match: a refusal phrased for a price the code accepted)."""
    key = (who, intent, tuple(numbers))
    if key in _cache:
        STATS.cache_hits += 1
        return _cache[key]
    llm = market_llm()
    if llm.provider == "mock":
        return fallback
    request = LLMRequest(
        system=SYSTEM.format(who=who, persona=persona or "naturel, commerçant."),
        messages=[ChatMessage(role="user", content=f"{intent}\nChiffres à citer tels quels : {', '.join(numbers) or 'aucun'}.\nTa réplique :")],
        max_tokens=140,
        thinking="disabled",
    )

    async def ask() -> str:
        out = ""
        async for ev in llm.stream(request):
            if isinstance(ev, LLMText):
                out += ev.delta
            elif isinstance(ev, LLMUsage):
                STATS.input_tokens += ev.input_tokens or 0
                STATS.output_tokens += ev.output_tokens or 0
        return out.strip().strip('"« »')

    STATS.llm_calls += 1
    t0 = time.perf_counter()
    try:
        text = await asyncio.wait_for(ask(), TIMEOUT_S)
    except Exception as e:
        STATS.fallbacks += 1
        print(f"[market] phrase fallback ({type(e).__name__}: {str(e)[:80]})", flush=True)
        return fallback
    finally:
        STATS.latencies_ms.append(int((time.perf_counter() - t0) * 1000))
    if not _ok(text, numbers) or (forbid and forbid.search(text)):
        STATS.fallbacks += 1
        return fallback
    if len(_cache) < CACHE_MAX:
        _cache[key] = text
    return text
