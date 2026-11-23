"""Turn numbers, prices, quantities and dates into spoken French, in code (GUIDE-VOIX 4.10).

The model should receive values that are already ready to say ("douze kilos", "dix-huit euros cinquante",
"jeudi vingt-six novembre") instead of "12.0 kg", "18.5 €", "2026-11-26". Pure functions, no I/O.

    from app.agent.speak_fr import say_number, say_price, say_qty, say_date
"""
from __future__ import annotations

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
