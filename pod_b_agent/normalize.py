"""French text normalisation: numbers-in-words, units, accents, a crude phonetic key.
Owned by Pod B. Pure functions, no I/O — easy to unit test."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from shared_contracts.schemas import Unit

# ───────── numbers ─────────
_UNITS_FR = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
    "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20,
    "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100,
}
_SPECIAL = {"douzaine": 12, "dizaine": 10, "quinzaine": 15, "vingtaine": 20, "centaine": 100}


def strip_accents(s: str) -> str:
    s = s.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _compound_to_int(tok: str) -> Optional[int]:
    """'vingt-quatre' -> 24, 'soixante-dix' -> 70, 'quatre-vingts' -> 80."""
    t = strip_accents(tok.lower())
    if t in _UNITS_FR:
        return _UNITS_FR[t]
    parts = [p for p in re.split(r"[-\s]", t) if p and p != "et"]
    if not parts or any(p.rstrip("s") not in _UNITS_FR for p in parts):
        return None
    total, current = 0, 0
    for p in parts:
        v = _UNITS_FR[p.rstrip("s")]
        if v == 100:
            current = max(current, 1) * 100
        elif v == 20 and current in (4,):          # quatre-vingt
            current = 80
        else:
            current += v
    return total + current


_NUM_WORD = r"(?:" + "|".join(sorted(_UNITS_FR, key=len, reverse=True)) + r")"
_COMPOUND_RE = re.compile(rf"\b{_NUM_WORD}s?(?:-(?:et-)?{_NUM_WORD}s?)+\b", re.I)
_SINGLE_RE = re.compile(rf"\b{_NUM_WORD}\b", re.I)


def words_to_numbers(text: str) -> str:
    """Rewrite French number words as digits, handling 'demi' forms.
    'un kilo et demi' -> '1.5 kilo', 'une demi-caisse' -> '0.5 caisse',
    'vingt-quatre' -> '24', 'une douzaine' -> '12'."""
    t = text
    t = re.sub(r"\b(?:un|une)\s+demie?[-\s]", "0.5 ", t, flags=re.I)
    t = re.sub(r"\b(?:une|la)\s+moiti[ée]\s+(?:d'un|d'une)\s+", "0.5 ", t, flags=re.I)
    t = re.sub(r"\b(?:une\s+)?(douzaine|dizaine|quinzaine|vingtaine|centaine)\s+(?:de\s+|d')",
               lambda m: f"{_SPECIAL[m.group(1).lower()]} ", t, flags=re.I)
    t = _COMPOUND_RE.sub(lambda m: str(_compound_to_int(m.group(0)) or m.group(0)), t)
    t = _SINGLE_RE.sub(lambda m: str(_UNITS_FR[strip_accents(m.group(0).lower())]), t)
    # "1 kilo et demi" / "2 et demi" -> 1.5 kilo / 2.5
    t = re.sub(r"\b(\d+)\s+([a-zéèû]+)\s+et\s+demie?\b",
               lambda m: f"{int(m.group(1)) + 0.5:g} {m.group(2)}", t, flags=re.I)
    t = re.sub(r"\b(\d+)\s+et\s+demie?\b", lambda m: f"{int(m.group(1)) + 0.5:g}", t, flags=re.I)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)   # 1,5 -> 1.5
    return t


# ───────── units ─────────
UNIT_PATTERNS: list[tuple[str, Unit]] = [
    (r"kilos?|kilogrammes?|kg", Unit.kg),
    (r"grammes?|gr", Unit.g),
    (r"pi[eè]ces?", Unit.piece),
    (r"bottes?", Unit.botte),
    (r"barquettes?", Unit.barquette),
    (r"plateaux?", Unit.plateau),
    (r"colis", Unit.colis),
    (r"cagettes?", Unit.cagette),
    (r"caisses?|cartons?", Unit.caisse),
    (r"sacs?", Unit.sac),
    (r"filets?(?=\s+(?:de|d'))", Unit.filet),   # "un filet d'oignons", not "lieu jaune en filet"
    (r"palettes?", Unit.palette),
    (r"litres?", Unit.litre),
    (r"bidons?", Unit.bidon),
]
UNIT_RE = "(?:" + "|".join(p for p, _ in UNIT_PATTERNS) + ")"


def parse_unit(s: Optional[str]) -> Optional[Unit]:
    if not s:
        return None
    for pat, unit in UNIT_PATTERNS:
        if re.fullmatch(pat.split("(?=")[0], s.strip(), flags=re.I):
            return unit
    return None


# ───────── product text normalisation ─────────
STOP = {"de", "d", "du", "des", "la", "le", "les", "l", "en", "a", "au", "aux", "un", "une",
        "mon", "ma", "mes", "ton", "ta", "tes", "the"}


def singular(tok: str) -> str:
    if len(tok) > 3 and tok.endswith(("s", "x")) and not tok.endswith(("ss",)):
        return tok[:-1]
    return tok


def norm_tokens(text: str) -> list[str]:
    t = strip_accents(text.lower())
    t = re.sub(r"[^a-z0-9%]+", " ", t)
    return [singular(w) for w in t.split() if w not in STOP]


def phon(tok: str) -> str:
    """Very small French phonetic key. faux/faut -> fo, barre/bar -> bar, lieux -> lieu."""
    w = strip_accents(tok.lower())
    for a, b in [("eau", "o"), ("au", "o"), ("ph", "f"), ("qu", "k"), ("ck", "k"),
                 ("ai", "e"), ("ei", "e"), ("y", "i"), ("oeu", "e"), ("w", "v")]:
        w = w.replace(a, b)
    w = re.sub(r"c(?=[eiy])", "s", w)
    w = w.replace("c", "k")
    w = re.sub(r"g(?=[ei])", "j", w)
    w = re.sub(r"(er|et|ez)$", "e", w)
    w = re.sub(r"(.)\1+", r"\1", w)
    if len(w) > 2:
        w = re.sub(r"[tdsxz]$", "", w)
    if len(w) > 2:
        w = re.sub(r"e$", "", w)
    return w
