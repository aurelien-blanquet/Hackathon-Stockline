"""Claude-based extractor (forced tool call -> strict JSON). Owned by Pod B.

Falls back to the rules extractor on any error/timeout so the live demo never stalls.
NOTE: written against the Anthropic Messages API tool-use format; not exercised offline —
run `make eval EXTRACTOR=llm` as soon as ANTHROPIC_API_KEY is set.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from .catalog import Catalog, load_catalog
from .extraction import Extraction, Mention
from .extractor_rules import extract_rules

log = logging.getLogger("pod_b.llm")

MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")      # fast default; try sonnet in eval
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "8"))

SYSTEM = """Tu es l'agent de saisie de commandes d'un grossiste alimentaire français (fruits & légumes, marée, boucherie, crèmerie).
On te donne la transcription (souvent bruitée, issue d'une reconnaissance vocale) d'un appel client.
Ta seule tâche : appeler l'outil submit_order avec les lignes de commande EXACTES.

Règles :
- Une ligne par produit commandé. N'invente jamais de produit ni de quantité.
- Garde la quantité et l'unité TELLES QUE DITES (ex: 2 cagettes, 3 kilos, 8 pièces). La conversion est faite après toi.
- unit = null si le client compte des pièces sans unité ("huit poulets", "deux bars").
- Corrections ("trois sacs, euh non, deux") : une seule ligne avec la valeur finale, action "add".
- Répétitions après une interruption : une seule ligne.
- "comme mardi dernier", "comme d'hab", "pareil que..." -> history_ref ("mardi", ..., ou "last").
  Les modifications ensuite : action "add" + increment=true pour "rajoute X en plus", action "set" pour une nouvelle quantité, action "remove" pour "enlève".
- Conditions ("si elles sont belles", "si t'en as") -> champ conditional, la ligne reste présente.
- Questions de prix -> price_questions. "m'en", "en mets" renvoie au dernier produit cité.
- sku_hint : le SKU du catalogue si tu es sûr, sinon null (produit absent du catalogue = null).
- Erreurs de transcription fréquentes : "barre" = bar (poisson), "faut filet" = faux-filet, "lieux jaunes" = lieu jaune, "mozza" = mozzarella.
"""

TOOL = {
    "name": "submit_order",
    "description": "Soumet les lignes de commande extraites de l'appel.",
    "input_schema": {
        "type": "object",
        "properties": {
            "history_ref": {"type": ["string", "null"], "description": "'last' ou jour de semaine en minuscules, sinon null"},
            "delivery_hint": {"type": ["string", "null"]},
            "price_questions": {"type": "array", "items": {"type": "string"}},
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "raw": {"type": "string", "description": "extrait exact de la transcription"},
                        "product_text": {"type": "string"},
                        "sku_hint": {"type": ["string", "null"]},
                        "quantity": {"type": ["number", "null"]},
                        "unit": {"type": ["string", "null"], "enum": [
                            "kg", "g", "piece", "botte", "barquette", "plateau", "colis", "cagette",
                            "caisse", "sac", "filet", "palette", "litre", "bidon", None]},
                        "action": {"type": "string", "enum": ["add", "set", "remove"]},
                        "increment": {"type": "boolean"},
                        "conditional": {"type": ["string", "null"]},
                    },
                    "required": ["raw", "product_text", "quantity", "unit", "action"],
                },
            },
        },
        "required": ["lines", "history_ref", "price_questions"],
    },
}

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # lazy: rules mode works without the SDK configured
        _client = anthropic.AsyncAnthropic(timeout=TIMEOUT_S, max_retries=1)
    return _client


async def extract_llm(transcript: str, customer: Optional[dict] = None,
                      catalog: Optional[Catalog] = None) -> Extraction:
    cat = catalog or load_catalog()
    if not os.getenv("ANTHROPIC_API_KEY"):
        return extract_rules(transcript, cat)
    usual = ""
    if customer and customer.get("orders"):
        last = customer["orders"][-1]
        usual = f"\nDernière commande du client ({last['date']}): " + json.dumps(last["lines"], ensure_ascii=False)
    user = (f"CATALOGUE (sku | libellé | alias | unité de vente | conditionnements):\n{cat.compact_listing()}\n"
            f"{usual}\n\nTRANSCRIPTION:\n\"\"\"{transcript}\"\"\"")
    try:
        resp = await _get_client().messages.create(
            model=MODEL, max_tokens=1500, system=SYSTEM,
            tools=[TOOL], tool_choice={"type": "tool", "name": "submit_order"},
            messages=[{"role": "user", "content": user}],
        )
        block = next(b for b in resp.content if getattr(b, "type", "") == "tool_use")
        data = block.input
        return Extraction(
            extractor="llm",
            history_ref=data.get("history_ref"),
            delivery_hint=data.get("delivery_hint"),
            price_questions=data.get("price_questions") or [],
            mentions=[Mention(**{k: v for k, v in ln.items() if v is not None or k in ("quantity", "unit")})
                      for ln in data.get("lines", [])],
        )
    except Exception as e:  # noqa: BLE001 — any failure => deterministic fallback
        log.warning("LLM extraction failed (%s) -> rules fallback", e)
        return extract_rules(transcript, cat)
