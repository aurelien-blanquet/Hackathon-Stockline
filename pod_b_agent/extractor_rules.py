"""Deterministic French order extractor. Owned by Pod B.

Role in the system: (1) offline fallback when the LLM is down / slow — the demo never dies,
(2) a baseline the LLM must beat in tests/eval.py. Handles: number words, units, corrections
("euh non pardon deux sacs"), pronoun "m'en", history references, removals, conditionals,
restatements after interruptions, price questions.
"""
from __future__ import annotations

import re
from typing import Optional

from .catalog import Catalog, load_catalog
from .extraction import Extraction, Mention
from .normalize import UNIT_RE, parse_unit, words_to_numbers

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
HISTORY_RE = re.compile(
    r"comme\s+(?:(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+dernier|"
    r"d'?hab(?:itude)?|la\s+derni[eè]re\s+fois|la\s+semaine\s+derni[eè]re)|pareil\s+que",
    re.I,
)
CORRECTION_RE = re.compile(r"\b(non\s+pardon|euh\s+non|non\s+non|plut[oô]t|enfin\s+non|je\s+veux\s+dire|finalement)\b", re.I)
REMOVE_RE = re.compile(r"\b(enl[eè]ve|retire|supprime|annule|pas\s+de|sans|oublie)\b", re.I)
INCREMENT_RE = re.compile(r"\b(rajoute|ajoute|en\s+plus|de\s+plus)\b", re.I)
PRONOUN_RE = re.compile(r"\b(m'en|j'en|en\s+mets|mets[- ]en|t'en)\b", re.I)
PRICE_RE = re.compile(r"(c'est\s+combien|quel\s+prix|[àa]\s+combien|combien\s+(?:il|elle|ils|elles)\s+(?:est|sont)|fais[- ]moi\s+un\s+prix)", re.I)
COND_RE = re.compile(
    r"\b(si\s+(?:elles?|ils?)\s+(?:sont|est)\s+\w+|si\s+(?:t'en\s+as|tu\s+en\s+as|y\s+en\s+a|il\s+y\s+en\s+a)\w*|"
    r"si\s+c'est\s+\w+)", re.I)
DELIVERY_RE = re.compile(r"\b(demain|apr[eè]s[- ]demain|" + "|".join(DAYS) + r")\b(?!\s+dernier)", re.I)

FILLERS = re.compile(
    r"\b(merci|s'il\s+te\s+pla[iî]t|s'il\s+vous\s+pla[iî]t|stp|svp|pour\s+demain|cette\s+fois|"
    r"en\s+plus|de\s+plus|entiers?|aussi|hein|quoi|voil[aà]|bon|ok|ouais|oui|euh|alors|"
    r"pour\s+la\s+viande|pour\s+le\s+poisson)\b", re.I)
LEAD = re.compile(r"^.*?\b(?:enl[eè]ve|retire|supprime|oublie|pas\s+de|sans)\b\s*", re.I)
PREP = re.compile(r"^(?:de\s+la\s+|de\s+l'|de\s+|d'|des\s+|du\s+|la\s+|le\s+|les\s+|l')", re.I)

QTY_RE = re.compile(rf"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>{UNIT_RE})?\b\s*(?P<rest>.*)", re.I)
SPLIT_RE = re.compile(r"[,;!?]+|\.(?!\d)|\s+et\s+(?!demi)|\s+puis\s+|\s+mais\s+", re.I)
MENTION_MIN_SCORE = 80.0


def _clean_product(text: str) -> str:
    t = COND_RE.sub(" ", text)
    t = FILLERS.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" -'")
    t = PREP.sub("", t).strip()
    return t


def extract_rules(transcript: str, catalog: Optional[Catalog] = None) -> Extraction:
    cat = catalog or load_catalog()
    text = re.sub(r"\[[^\]]*\]", " ", transcript)            # [bruit chambre froide]
    text = text.replace("’", "'").replace("\n", " ")
    text = words_to_numbers(text)
    # times are not quantities: "avant 6 heures" would otherwise fuzzy-match "beurre"
    text = re.sub(r"\b(?:avant|vers|pour|[àa])?\s*\d{1,2}\s*(?:h|heures?)(?:\s*\d{2})?\b", " ", text, flags=re.I)

    ex = Extraction(extractor="rules")
    if (m := HISTORY_RE.search(text)):
        ex.history_ref = (m.group(1) or "last").lower()
    if (d := DELIVERY_RE.search(text)):
        ex.delivery_hint = d.group(1).lower()

    last_mention: Optional[str] = None                       # product text without qty yet
    for clause in (c.strip() for c in SPLIT_RE.split(text) if c and c.strip()):
        if PRICE_RE.search(clause):
            prod = _clean_product(PRICE_RE.sub(" ", clause).replace("le ", " ", 1))
            prod = re.sub(r"\ben\s+ce\s+moment\b", "", prod).strip()
            if prod:
                ex.price_questions.append(prod)
                last_mention = prod
            continue

        cond = (cm.group(0) if (cm := COND_RE.search(clause)) else None)
        qm = QTY_RE.search(clause)

        if not qm:
            # no quantity: removal, or a product mentioned before its quantity ("des poivrons, 2 colis")
            if HISTORY_RE.search(clause):
                continue
            prod = _clean_product(LEAD.sub("", clause) if REMOVE_RE.search(clause) else clause)
            if not prod:
                continue
            if REMOVE_RE.search(clause):
                ex.mentions.append(Mention(raw=clause, product_text=prod, action="remove"))
            elif cat.match(prod).score >= MENTION_MIN_SCORE:
                last_mention = prod
            continue

        qty = float(qm.group("qty"))
        unit = parse_unit(qm.group("unit"))
        prod = _clean_product(qm.group("rest"))
        prod = PRONOUN_RE.sub("", prod).strip()
        is_correction = bool(CORRECTION_RE.search(clause))

        if not prod:
            if is_correction and ex.mentions:
                prev = ex.mentions[-1]
                ex.mentions.append(Mention(raw=clause, product_text=prev.product_text, quantity=qty,
                                           unit=(unit.value if unit else prev.unit), action="set"))
            elif last_mention:
                ex.mentions.append(Mention(raw=clause, product_text=last_mention, quantity=qty,
                                           unit=unit.value if unit else None, conditional=cond))
                last_mention = None
            continue

        # restatement after an interruption ("5 kilos de cabillaud ... oui pardon, 5 kilos de cabillaud")
        if any(m.product_text == prod and m.quantity == qty and m.action != "remove" for m in ex.mentions) \
                and not INCREMENT_RE.search(clause):
            continue

        ex.mentions.append(Mention(
            raw=clause, product_text=prod, quantity=qty, unit=unit.value if unit else None,
            action="set" if is_correction else "add",
            increment=bool(INCREMENT_RE.search(clause)), conditional=cond,
        ))
        last_mention = None
    return ex
