"""
Two models for the voice agent, chosen per turn in code (no extra call, no latency): the fast one (Haiku) when the
code already did the structured work, the strong one (LLM_MODEL, Sonnet) when the turn needs judgement.

VOICE_FAST_MODEL=claude-haiku-5-5 turns it on; empty = LLM_MODEL for every turn (as before).

Why: after the preload (services/fast_path.py) the caller is identified, the products resolved with stock and
price, the draft written or the market negotiated: the model only has to say it in one sentence. That is Haiku's
job (~0.5 s to the first word vs ~1 s, a fraction of the price). A complaint, a change of mind, a refusal, a blocked
client, a long or unidentified request are where Sonnet's judgement pays.
"""

import re
from dataclasses import replace
from functools import cache

from app.agent.guardrails import CORRECTION, NEGATIVE
from app.clients import LLMClient
from app.clients.factory import make_llm_client
from app.config import env, settings
from app.schemas import ChatMessage

FAST_MODEL = env("VOICE_FAST_MODEL")
SHORT_WORDS = 12  # a short follow-up in an identified call (« et si j'en prends dix ? »)

# Turns that need judgement: a complaint, a dispute, a refusal, something wrong.
HARD = re.compile(
    r"pas bon|mauvais|abîm|abim|avoir\b|réclam|reclam|problème|probleme|jet[ée]|erreur|retard|manqu|pourri|plainte|"
    r"pas content|inadmissible|rembours|annul|humain|responsable|patron",
    re.I,
)


@cache
def fast_client() -> LLMClient | None:
    if not FAST_MODEL or settings.llm.provider == "mock":
        return None
    return make_llm_client(replace(settings.llm, model=FAST_MODEL))


def route(strong: LLMClient, heard: str, history: list[ChatMessage], preloaded: bool, optimistic: bool, blocked: bool,
          fast: LLMClient | None = None) -> tuple[LLMClient, str]:
    """(client, reason) for this turn: `strong` (LLM_MODEL) or the fast model. `history` = the call before this turn."""
    fast = fast or fast_client()
    if fast is None:
        return strong, "one model"
    if blocked:
        return strong, "blocked client"
    if HARD.search(heard):
        return strong, "complaint / dispute"
    if optimistic:  # a plain yes to a recap: write + confirm
        return fast, "yes"
    if CORRECTION.search(heard) or NEGATIVE.search(heard):
        return strong, "change of mind"
    if preloaded:
        return fast, "preloaded"
    identified = any(m.role == "tool" and m.name == "identify_caller" for m in history)
    if identified and len(heard.split()) <= SHORT_WORDS:
        return fast, "short follow-up"
    return strong, "open request"
