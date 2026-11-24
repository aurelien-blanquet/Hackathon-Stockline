"""
Negotiation levers, learned per supplier: the buyer agent remembers WHICH argument moves each producer, and uses it.

A lever is what the buyer offers in exchange for a lower price:
    concurrence   « J'ai une offre à 12,37 € ailleurs »      — the rival's price (the only lever before this module)
    volume        « on vous prend tout en une livraison »    — bigger single order
    fidelite      « on vous engage sur la saison »           — commitment over time
    paiement      « réglé à la livraison, pas à 30 jours »   — cash now
    souplesse     « on se cale sur votre prochaine tournée » — they choose the delivery day (not when urgent)

Each supplier has a hidden sensitivity to each lever (0–1), a stable trait: a little from its sheet (« négocie sur
les volumes », « trésorerie », « fidélité »…), the rest drawn once from its id. The buyer never reads it: it only sees
what a lever obtained (the price drop after using it). `LeverMemory` keeps, per supplier and lever, how many times it
was tried and the mean drop obtained, and picks the next lever by UCB (try each once, then mostly the best one).
So round after round the buyer opens with the lever that works on THIS supplier, then adds the competitor's price.

Persisted as JSON (MARKET_MEMORY, default .market-memory.json next to the service): it survives restarts, and
`reset()` starts a fresh learning curve for a demo.
"""

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.config import env

LEVERS = ("concurrence", "volume", "fidelite", "paiement", "souplesse")
LABELS = {"concurrence": "prix concurrent", "volume": "volume", "fidelite": "fidélité", "paiement": "paiement rapide",
          "souplesse": "livraison souple"}  # fmt: skip

# What the supplier sheet says that hints at a lever (it raises the hidden sensitivity, it does not set it)
HINTS = {
    "concurrence": re.compile(r"concurren|s'aligne|aligner|comparer", re.I),
    "volume": re.compile(r"volume|quantit|palette|tonne|gros|en gros", re.I),
    "fidelite": re.compile(r"fidél|fidel|habitu|depuis \d|confiance|engagement|relation", re.I),
    "paiement": re.compile(r"paie|paye|règlement|reglement|trésorerie|tresorerie|comptant|délai de paiement", re.I),
    "souplesse": re.compile(r"tournée|tournee|camion|délai|delai|planning|livraison groupée", re.I),
}

MAX_EXTRA = 0.035  # a fully effective lever: 3.5 % more than the usual small gesture…
FLOOR_EXTRA = 0.03  # …and the supplier's floor moves down by up to 3 %
UCB_C = 0.012  # exploration weight (in price-drop units: ~1 %)


def buyer_line(lever: str | None, product: str, rival_price: str | None, first: bool, urgent: bool = False) -> str:
    """What the buyer says to use a lever (the competitor's NAME is never said, only its price)."""
    match lever:
        case "concurrence" if rival_price:
            return (f"J'ai une offre à {rival_price} ailleurs sur {product}. Vous pouvez vous aligner ?" if first
                    else f"On me fait toujours {rival_price} ailleurs sur {product}. Un dernier effort ?")  # fmt: skip
        case "volume":
            return f"Si on vous prend tout le volume de {product} en une seule livraison, vous faites combien ?"
        case "fidelite":
            return f"On travaille ensemble toute l'année : si je m'engage avec vous sur la saison pour {product}, vous faites un effort ?"
        case "paiement":
            return f"Je peux vous régler à la livraison plutôt qu'à trente jours : ça vous permet de descendre sur {product} ?"
        case "souplesse":
            return f"Si on se cale sur votre prochaine tournée au lieu d'une livraison dédiée, vous baissez {product} ?"
    if urgent:
        return f"C'est pour dépanner un bon client : vous faites un geste sur {product} ?"
    return f"Sur ces volumes, vous pouvez faire un geste sur {product} ?" if first else f"Et si on vous prend tout le volume sur {product}, vous descendez encore ?"


def _unit(seed: str) -> float:
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def sensitivity(supplier_id: str, persona: str, fixed_price: bool) -> dict[str, float]:
    """The supplier's hidden response to each lever, 0–1. Fixed-price suppliers move on nothing."""
    if fixed_price:
        return {lever: 0.0 for lever in LEVERS}
    out = {}
    for lever in LEVERS:
        s = 0.1 + 0.6 * _unit(f"lever|{supplier_id}|{lever}")
        if HINTS[lever].search(persona or ""):
            s += 0.35
        out[lever] = round(min(1.0, s), 3)
    return out


def available(urgent: bool, has_rival: bool) -> tuple[str, ...]:
    """What the buyer can honestly offer on this call: no « on choisit votre jour » when the customer is waiting, no
    competitor argument without a competitor's price."""
    return tuple(lv for lv in LEVERS if not (lv == "souplesse" and urgent) and not (lv == "concurrence" and not has_rival))


@dataclass
class Stat:
    n: int = 0
    mean: float = 0.0  # mean relative price drop obtained (0.02 = 2 %)

    def add(self, drop: float) -> None:
        self.n += 1
        self.mean += (drop - self.mean) / self.n


@dataclass
class LeverMemory:
    """What the buyer learned, per supplier: lever → Stat."""

    stats: dict[str, dict[str, Stat]] = field(default_factory=dict)
    path: Path | None = None
    rounds: int = 0  # negotiations learned from (for the page / the curve)

    def choose(self, supplier_id: str, options: tuple[str, ...]) -> str | None:
        """UCB: a lever never tried on this supplier first (in LEVERS order), then the best mean + a small exploration
        bonus. Deterministic (same memory → same choice)."""
        if not options:
            return None
        mine = self.stats.get(supplier_id, {})
        untried = [lv for lv in options if mine.get(lv, Stat()).n == 0]
        if untried:
            return untried[0]
        total = sum(mine[lv].n for lv in options)
        return max(options, key=lambda lv: mine[lv].mean + UCB_C * math.sqrt(math.log(total + 1) / mine[lv].n))

    def best(self, supplier_id: str) -> str | None:
        mine = {lv: s for lv, s in self.stats.get(supplier_id, {}).items() if s.n}
        return max(mine, key=lambda lv: mine[lv].mean) if mine else None

    def record(self, supplier_id: str, lever: str, drop: float) -> None:
        self.stats.setdefault(supplier_id, {}).setdefault(lever, Stat()).add(max(0.0, drop))

    def learn(self, script) -> None:
        """Every counter of a negotiation (express.Script) whose lever is known → one observation."""
        for sid, steps in script.steps.items():
            for st in steps:
                if st.kind == "counter" and st.lever and st.before:
                    self.record(sid, st.lever, (st.before - st.after) / st.before)
        self.rounds += 1
        self.save()

    def summary(self, names: dict[str, str] | None = None) -> list[dict]:
        out = []
        for sid, levers in sorted(self.stats.items()):
            best = self.best(sid)
            out.append({"supplierId": sid, "name": (names or {}).get(sid, sid), "best": best, "bestLabel": LABELS.get(best or "", ""),
                        "levers": {lv: {"tries": s.n, "meanDropPct": round(100 * s.mean, 2)} for lv, s in levers.items()}})  # fmt: skip
        return out

    # ── persistence ──

    def save(self) -> None:
        if not self.path:
            return
        try:
            data = {"rounds": self.rounds, "stats": {sid: {lv: [s.n, s.mean] for lv, s in lv_.items()} for sid, lv_ in self.stats.items()}}
            self.path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as e:
            print(f"[market] lever memory not saved: {e}", flush=True)

    @classmethod
    def load(cls, path: Path | None) -> "LeverMemory":
        m = cls(path=path)
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                m.rounds = data.get("rounds", 0)
                m.stats = {sid: {lv: Stat(n, mean) for lv, (n, mean) in lv_.items()} for sid, lv_ in data.get("stats", {}).items()}
            except (OSError, ValueError, TypeError) as e:
                print(f"[market] lever memory unreadable, starting fresh: {e}", flush=True)
        return m

    def reset(self) -> None:
        self.stats, self.rounds = {}, 0
        self.save()


MEMORY = LeverMemory.load(Path(env("MARKET_MEMORY", ".market-memory.json")))
