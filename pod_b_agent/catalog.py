"""Catalog loading + fuzzy/phonetic SKU matcher. Owned by Pod B.

Scoring = 0.7 * query-token coverage + 0.3 * candidate-token coverage, where each token
similarity is max(ratio on normalised text, ratio on phonetic key). Exact alias hit = 100.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz

from shared_contracts.schemas import Candidate, Unit

from .normalize import norm_tokens, phon

ROOT = Path(__file__).resolve().parents[1]
MATCH_THRESHOLD = 72.0      # below -> UNKNOWN_SKU
AMBIGUITY_GAP = 6.0         # top-2 within this gap (and both above threshold) -> AMBIGUOUS_SKU


@dataclass
class Product:
    sku: str
    label: str
    aliases: list[str]
    category: str
    sell_unit: Unit
    conversions: dict[str, tuple[float, bool]]  # unit -> (factor in sell units, is_estimate)
    price_eur: float
    stock: float
    substitutes: list[str]
    _keys: list[list[str]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._keys = [norm_tokens(n) for n in [self.label, *self.aliases] if n]


@dataclass
class MatchResult:
    product: Optional[Product]
    score: float
    candidates: list[Candidate]
    ambiguous: bool

    @property
    def matched(self) -> bool:
        return self.product is not None and self.score >= MATCH_THRESHOLD


def _parse_conversions(raw: str) -> dict[str, tuple[float, bool]]:
    out: dict[str, tuple[float, bool]] = {}
    for part in filter(None, (raw or "").split(";")):
        unit, val = part.split("=")
        est = val.startswith("~")
        out[unit.strip()] = (float(val.lstrip("~")), est)
    return out


def _tok_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return max(fuzz.ratio(a, b), fuzz.ratio(phon(a), phon(b))) / 100.0


def _score(q: list[str], c: list[str]) -> float:
    if not q or not c:
        return 0.0
    if q == c or [phon(t) for t in q] == [phon(t) for t in c]:
        return 100.0
    q_cov = sum(max(_tok_sim(a, b) for b in c) for a in q) / len(q)
    c_cov = sum(max(_tok_sim(b, a) for a in q) for b in c) / len(c)
    return 100.0 * (0.7 * q_cov + 0.3 * c_cov)


class Catalog:
    def __init__(self, products: list[Product]):
        self.products = products
        self.by_sku = {p.sku: p for p in products}

    @classmethod
    def from_csv(cls, path: Path) -> "Catalog":
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        return cls([
            Product(
                sku=r["sku"], label=r["label"],
                aliases=[a for a in (r.get("aliases") or "").split("|") if a],
                category=r.get("category", ""), sell_unit=Unit(r["sell_unit"]),
                conversions=_parse_conversions(r.get("conversions", "")),
                price_eur=float(r.get("price_eur") or 0), stock=float(r.get("stock") or 0),
                substitutes=[s for s in (r.get("substitutes") or "").split("|") if s],
            ) for r in rows
        ])

    def match(self, text: str, top_k: int = 3) -> MatchResult:
        q = norm_tokens(text)
        scored = sorted(
            ((max(_score(q, k) for k in p._keys), p) for p in self.products),
            key=lambda x: x[0], reverse=True,
        )
        cands = [Candidate(sku=p.sku, label=p.label, score=round(s, 1)) for s, p in scored[:top_k]]
        if not scored:
            return MatchResult(None, 0, [], False)
        best_s, best = scored[0]
        second_s = scored[1][0] if len(scored) > 1 else 0
        ambiguous = best_s < 100 and best_s >= MATCH_THRESHOLD and (best_s - second_s) < AMBIGUITY_GAP
        return MatchResult(best if best_s >= MATCH_THRESHOLD else None, best_s, cands, ambiguous)

    def compact_listing(self) -> str:
        """One line per SKU, for LLM prompts."""
        lines = []
        for p in self.products:
            conv = ",".join(f"{u}={'~' if e else ''}{f:g}" for u, (f, e) in p.conversions.items())
            lines.append(f"{p.sku} | {p.label} | {'/'.join(p.aliases)} | vendu au {p.sell_unit.value} | {conv}")
        return "\n".join(lines)


@lru_cache
def load_catalog(path: str | None = None) -> Catalog:
    return Catalog.from_csv(Path(path) if path else ROOT / "data" / "catalog_sample.csv")


@lru_cache
def load_customers(path: str | None = None) -> dict[str, dict]:
    p = Path(path) if path else ROOT / "data" / "customers_sample.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return {c["customer_id"]: c for c in data["customers"]}
