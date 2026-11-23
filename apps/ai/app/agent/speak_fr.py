"""Turn numbers, prices, quantities and dates into spoken French, in code (GUIDE-VOIX 4.10).

The model should receive values that are already ready to say ("douze kilos", "dix-huit euros cinquante",
"jeudi vingt-six novembre") instead of "12.0 kg", "18.5 €", "2026-11-26". Pure functions, no I/O.

    from app.agent.speak_fr import say_number, say_price, say_qty, say_date
"""
from __future__ import annotations

import re
from datetime import date

_UNITS = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
          "treize", "quatorze", "quinze", "seize"]
_TENS = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante"}
_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"]


def _below_100(n: int) -> str:
    if n <= 16:
        return _UNITS[n]
    if n < 20:
        return "dix-" + _UNITS[n - 10]
    if n < 70:
        tens, unit = divmod(n, 10)
        word = _TENS[tens * 10]
        if unit == 0:
            return word
        return f"{word} et un" if unit == 1 else f"{word}-{_UNITS[unit]}"
    if n < 80:                                   # 70-79: soixante-dix, soixante et onze…
        return "soixante et onze" if n == 71 else "soixante-" + _below_100(n - 60)
    if n == 80:
        return "quatre-vingts"
    return "quatre-vingt-" + _below_100(n - 80)  # 81-99: quatre-vingt-un, quatre-vingt-dix…


def _below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        return _below_100(rest)
    head = "cent" if hundreds == 1 else f"{_UNITS[hundreds]} cent" + ("s" if rest == 0 else "")
    return head if rest == 0 else f"{head} {_below_100(rest)}"


def say_int(n: int) -> str:
    """Integer in words (0 to 999 999 999). 'quatre-vingts' takes its s only when it ends the number."""
    if n < 0:
        return "moins " + say_int(-n)
    if n < 1000:
        return _below_1000(n)
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        head = "mille" if thousands == 1 else _below_1000(thousands).replace("cents", "cent").replace(
            "quatre-vingts", "quatre-vingt") + " mille"
        return head if rest == 0 else f"{head} {_below_1000(rest)}"
    millions, rest = divmod(n, 1_000_000)
    head = "un million" if millions == 1 else f"{_below_1000(millions)} millions"
    return head if rest == 0 else f"{head} {say_int(rest)}"


def say_number(x: float, decimals: int = 2) -> str:
    """12 -> 'douze', 1.5 -> 'un virgule cinq', 2.25 -> 'deux virgule vingt-cinq'."""
    x = round(float(x), decimals)
    if x == int(x):
        return say_int(int(x))
    sign = "moins " if x < 0 else ""
    whole, frac = f"{abs(x):.{decimals}f}".split(".")
    frac = frac.rstrip("0")
    frac_words = " ".join(_UNITS[int(d)] for d in frac) if frac.startswith("0") else say_int(int(frac))
    return f"{sign}{say_int(int(whole))} virgule {frac_words}"


def say_price(eur: float, per: str | None = None) -> str:
    """18.5 -> 'dix-huit euros cinquante', 0.9 -> 'quatre-vingt-dix centimes', per='kilo' -> '… le kilo'."""
    cents_total = round(float(eur) * 100)
    euros, cents = divmod(cents_total, 100)
    if euros == 0:
        out = f"{say_int(cents)} centime{'s' if cents > 1 else ''}"
    else:
        out = f"{say_int(euros)} euro{'s' if euros > 1 else ''}"
        if cents:
            out += f" {say_int(cents)}"
    return f"{out} le {per}" if per else out


_UNIT_WORDS = {   # unit code -> (singular, plural)
    "kg": ("kilo", "kilos"), "g": ("gramme", "grammes"), "l": ("litre", "litres"), "litre": ("litre", "litres"),
    "piece": ("pièce", "pièces"), "pc": ("pièce", "pièces"), "u": ("pièce", "pièces"),
    "colis": ("colis", "colis"), "carton": ("carton", "cartons"), "caisse": ("caisse", "caisses"),
    "cagette": ("cagette", "cagettes"), "botte": ("botte", "bottes"), "barquette": ("barquette", "barquettes"),
    "plateau": ("plateau", "plateaux"), "sac": ("sac", "sacs"), "douzaine": ("douzaine", "douzaines"),
    "meule": ("meule", "meules"), "pot": ("pot", "pots"), "seau": ("seau", "seaux"),
    # the ERP's own unit codes (apps/backend/app/schemas/domain.py: kg | piece | box | dozen | liter)
    "box": ("carton", "cartons"), "dozen": ("douzaine", "douzaines"), "liter": ("litre", "litres"),
    "pièce": ("pièce", "pièces"), "pièces": ("pièce", "pièces"), "kilo": ("kilo", "kilos"), "kilos": ("kilo", "kilos"),
    "cartons": ("carton", "cartons"), "litres": ("litre", "litres"),
}


def say_qty(qty: float, unit: str | None = None) -> str:
    """(12, 'kg') -> 'douze kilos', (1.5, 'kg') -> 'un kilo et demi', (1, 'meule') -> 'une meule'."""
    unit_key = (unit or "").strip().lower()
    sing, plur = _UNIT_WORDS.get(unit_key, (unit_key, unit_key))
    q = round(float(qty), 3)
    feminine = sing in {"pièce", "caisse", "cagette", "botte", "barquette", "douzaine", "meule"}
    if q == int(q):
        n = int(q)
        words = ("une" if feminine else "un") if n == 1 else say_int(n)
        return f"{words} {sing if n <= 1 else plur}".strip()
    if q * 2 == int(q * 2) and q > 1:                         # 1.5 -> un kilo et demi
        n = int(q)
        words = ("une" if feminine else "un") if n == 1 else say_int(n)
        return f"{words} {sing if n == 1 else plur} et demi{'e' if feminine else ''}".strip()
    if q == 0.5:
        return f"une demi-{sing}" if feminine else f"un demi-{sing}"
    return f"{say_number(q)} {plur}".strip()


def say_date(iso: str | date, today: str | date | None = None) -> str:
    """'2026-11-26' -> 'jeudi vingt-six novembre'; with today, 'demain' / 'aujourd'hui' when it applies.
    Always pass the ERP business date (GET /api/meta -> today), never the real date."""
    d = iso if isinstance(iso, date) else date.fromisoformat(str(iso)[:10])
    if today is not None:
        t = today if isinstance(today, date) else date.fromisoformat(str(today)[:10])
        delta = (d - t).days
        if delta == 0:
            return "aujourd'hui"
        if delta == 1:
            return "demain"
        if delta == 2:
            return "après-demain"
    day = "premier" if d.day == 1 else say_int(d.day)
    return f"{_DAYS[d.weekday()]} {day} {_MONTHS[d.month - 1]}"


def say_order_ref(number: str, keep: int = 3) -> str:
    """Never read full ids aloud (GUIDE-VOIX 5.5): 'CMD-2026-000124' -> 'la commande cent vingt-quatre'."""
    digits = "".join(c for c in number.split("-")[-1] if c.isdigit()).lstrip("0") or "0"
    return f"la commande {say_int(int(digits[-keep:]))}"


# ── Whole replies → text a TTS reads correctly ───────────────────────────────────────────────────────────────────
# Whatever the model writes ("18.50 €/kg", "2026-11-26", "**Reblochon**", "cli_0012", "6:00", "12 kg"), the voice
# must say it like a salesperson. Applied to every sentence just before TTS (services/voice_session.py), so the
# transcript on screen keeps the model's text and only the audio is normalised.

_NUM = r"\d+(?:[.,]\d+)?"
_PER = r"(?:\s?(?:/|le|la|par)\s?(kg|kilo|pièce|piece|pce|l|litre|douzaine|carton|boîte|box|unité))?"
_UNIT_RE = r"kg|kilos?|g|grammes?|l|litres?|pièces?|pcs?|cartons?|douzaines?|meules?|plateaux?|seaux?|caisses?"
_PER_WORD = {"kg": "kilo", "kilo": "kilo", "pièce": "pièce", "piece": "pièce", "pce": "pièce", "l": "litre",
             "litre": "litre", "douzaine": "douzaine", "carton": "carton", "boîte": "boîte", "box": "carton",
             "unité": "unité"}
_TECH_ID = re.compile(r"\s*\(?\b(?:cli|prd|sup|ord|lin|po|inv|rte|ctx|evt|pay)_[A-Za-z0-9_]+\)?", re.IGNORECASE)
_ORDER_NO = re.compile(r"\b(?:CMD|ACH|FAC)-\d{4}-(\d+)\b")
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})(?:T[\d:.]+Z?)?\b")
_PRICE = re.compile(rf"({_NUM})\s?(?:€|euros?\b|EUR\b){_PER}", re.IGNORECASE)
_QTY = re.compile(rf"\b({_NUM})\s?({_UNIT_RE})\b(?!\s?(?:€|/))", re.IGNORECASE)
_TIME = re.compile(r"\b([01]?\d|2[0-3])\s?(?:h|:)\s?([0-5]\d)?\b(?!\s?(?:kg|€))")
_PERCENT = re.compile(rf"({_NUM})\s?%")
_DOT_DECIMAL = re.compile(r"\b(\d+)\.(\d+)\b")


_FEMININE = {"pièce", "douzaine", "boîte", "unité", "meule", "caisse"}


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _price(m: re.Match) -> str:
    per = _PER_WORD.get((m[2] or "").lower())
    spoken = say_price(_num(m[1]))
    if not per:
        return spoken
    return f"{spoken} {'la' if per in _FEMININE else 'le'} {per}"


def _qty(m: re.Match) -> str:
    unit = m[2].lower()
    unit = {"g": "g", "gramme": "g", "grammes": "g", "l": "l", "pcs": "piece", "pc": "piece"}.get(unit, unit)
    return say_qty(_num(m[1]), unit)


def _time(m: re.Match) -> str:
    h, mins = int(m[1]), int(m[2] or 0)
    hours = "une heure" if h == 1 else ("minuit" if h == 0 else f"{say_int(h)} heures")
    if h == 12 and m[2] is None:
        hours = "midi"
    return hours if not mins else f"{hours} {'et demie' if mins == 30 else say_int(mins)}"


def to_speech(text: str, today: str | date | None = None) -> str:
    """'Le reblochon est à 9.40 €/pièce, livraison 2026-11-26 avant 6:00.' →
    'Le reblochon est à neuf euros quarante la pièce, livraison jeudi vingt-six novembre avant six heures.'"""
    t = text
    t = _TECH_ID.sub("", t)                                               # cli_0012, prd_0003 never read aloud
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)                          # links → their text
    t = re.sub(r"[*_`#>]+", "", t)                                        # markdown
    t = re.sub(r"^\s*(?:[-•]|\d+[.)])\s+", "", t, flags=re.MULTILINE)               # bullets, numbered lists
    t = re.sub(r"\s*\n+\s*", ", ", t.strip())                               # one line per item → a spoken list
    t = _ORDER_NO.sub(lambda m: f"numéro {say_int(int(m[1].lstrip('0')[-3:] or '0'))}", t)
    t = _ISO_DATE.sub(lambda m: say_date(m[1], today), t)
    t = _PRICE.sub(_price, t)
    t = _PERCENT.sub(lambda m: f"{say_number(_num(m[1]))} pour cent", t)
    t = _QTY.sub(_qty, t)
    t = _TIME.sub(_time, t)
    t = _DOT_DECIMAL.sub(r"\1,\2", t)                                     # 2.5 → 2,5 (French TTS reads it right)
    t = re.sub(r"\bHT\b", "hors taxes", t)
    t = re.sub(r"\bTTC\b", "toutes taxes comprises", t)
    t = re.sub(r"\bAOP\b", "A O P", t)
    t = re.sub(r"\bIGP\b", "I G P", t)
    t = t.replace("&", " et ").replace(" / ", ", ")
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"\s+([,.…])", r"\1", t)  # (French keeps its space before ! ? ; :)
    return re.sub(r"[ \t]{2,}", " ", t).strip()
