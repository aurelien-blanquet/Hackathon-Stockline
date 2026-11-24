"""
What the agents SAY on the market calls. The numbers come from strategy.py; a model only phrases them in the speaker's
own voice (the supplier sheet: how they talk, their tics). Guard: every number it was given must appear verbatim in
its sentence, else the template is used. Mock provider, timeout or error → template: the market runs without keys.
"""

import asyncio
import re

from app.clients import LLMRequest, LLMText, get_llm_client
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


# A line that must say « yes » cannot sound like « no »: the code decided, the voice follows.
REFUSAL = re.compile(r"\b(non|peux pas|pas possible|impossible|refuse)\b", re.IGNORECASE)


async def phrase(who: str, persona: str, intent: str, numbers: list[str], fallback: str, forbid: re.Pattern | None = None) -> str:
    """The line `who` says to do `intent`, with these exact numbers. The template on any doubt (missing number,
    or a `forbid` match: a refusal phrased for a price the code accepted)."""
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
        return out.strip().strip('"« »')

    try:
        text = await asyncio.wait_for(ask(), TIMEOUT_S)
    except Exception as e:
        print(f"[market] phrase fallback ({type(e).__name__}: {str(e)[:80]})", flush=True)
        return fallback
    return text if _ok(text, numbers) and not (forbid and forbid.search(text)) else fallback
