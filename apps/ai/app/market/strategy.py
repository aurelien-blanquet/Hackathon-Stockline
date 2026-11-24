"""
The numbers of the market, in code: no model decides a price, a quantity or who wins. The agents only SAY them.

    SupplierProfile    from the ERP: lead time, minimum order, reliability ★ and flexibility ★ (supplier sheet), incidents
    supplier_terms()   what one supplier can do on one product: opening price, floor (never below), capacity
    counter()          the supplier's answer to « X me fait Y, vous pouvez faire mieux ? »
    allocate()         the central decision: cheapest cover per product, penalised by unreliability, within
                       capacities, then minimum orders; what stays uncovered is reported, never hidden
"""

import hashlib
import re
from dataclasses import dataclass, field

STARS = re.compile(r"Fiabilit[ée][^★☆]*(★+)(☆*)[^★☆]*souplesse[^★☆]*(★+)(☆*)", re.IGNORECASE)


@dataclass
class SupplierProfile:
    id: str
    name: str
    lead_time_days: int = 1
    min_order: float = 0.0
    reliability: int = 2  # ★ 1–3 (supplier sheet « Fiabilité »)
    flexibility: int = 2  # ★ 1–3 (« souplesse »): how far they move on price
    issues_12m: int = 0
    contact: str = ""
    persona: str = ""  # how they talk, tics, negotiation habits (for the voice only)
    fixed_price: bool = False  # supplier sheet « Prix fixe … / aucune remise »: quotes its list price, never moves


FIXED = re.compile(r"prix fixe|aucune remise|sans remise", re.IGNORECASE)


def is_fixed_price(negotiation_text: str) -> bool:
    """« Prix fixe à l'année, aucune remise. » → True."""
    return bool(FIXED.search(negotiation_text or ""))


def parse_stars(profile_text: str) -> tuple[int, int]:
    """« Fiabilité : ★★☆ — souplesse ★★★ » → (2, 3). (2, 2) when absent."""
    m = STARS.search(profile_text or "")
    return (len(m.group(1)), len(m.group(3))) if m else (2, 2)


@dataclass
class NeedLine:
    product_id: str
    name: str
    unit: str
    category: str
    cost: float  # our usual purchase cost (reference for the savings)
    need: float
    list_prices: dict[str, float] = field(default_factory=dict)  # supplier id → price-list price

    @property
    def reference_price(self) -> float:
        """What we pay without negotiating: the best price-list price (our cost when no list price)."""
        return min(self.list_prices.values()) if self.list_prices else self.cost


@dataclass
class Terms:
    """One supplier, one product: private to that supplier (the buyer only sees the offers)."""

    opening: float
    floor: float
    capacity: float
    regular: bool  # it is on their price list (their usual product)


@dataclass
class Offer:
    supplier_id: str
    product_id: str
    price: float
    qty: float
    final: bool = False
    opening: float | None = None  # the price first asked on this call (what the negotiation saved is measured from it)


def _unit(seed: str) -> float:
    """Deterministic 0..1 from a string (same round seed → same market)."""
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _round_qty(qty: float, unit: str) -> float:
    return round(qty, 1) if unit == "kg" or unit == "liter" else float(int(qty))


def supplier_terms(s: SupplierProfile, line: NeedLine, seed: str = "") -> Terms:
    r = _unit(f"{seed}|{s.id}|{line.product_id}")
    regular = s.id in line.list_prices
    ref = line.list_prices.get(s.id) or round(line.cost * (1.05 + 0.06 * r), 2)  # not their usual product: dearer
    opening = round(ref * (1.02 + 0.03 * r), 2)  # they always ask a little above their list
    floor = round(ref * (1 - {1: 0.01, 2: 0.03, 3: 0.06}.get(s.flexibility, 0.03)), 2)
    if s.fixed_price:  # « prix fixe, aucune remise »: their list, no haggling either way
        opening = floor = round(ref, 2)
    share = (0.65 + 0.35 * r) if regular else (0.2 + 0.35 * r)  # Christmas volumes: nobody covers everything alone
    return Terms(opening=opening, floor=floor, capacity=_round_qty(line.need * share, line.unit), regular=regular)


def counter(terms: Terms, current: float, competitor: float | None) -> tuple[float, bool]:
    """The supplier's next price and whether it is final. Matches a better competitor down to its floor; without
    competition, a small volume gesture. Final when the floor is reached."""
    target = competitor - 0.01 if competitor is not None and competitor < current else current * 0.985
    price = round(max(terms.floor, min(current, target)), 2)
    return price, price <= terms.floor + 0.005


@dataclass
class Allocation:
    supplier_id: str
    product_id: str
    qty: float
    price: float
    opening: float  # what this supplier first asked


@dataclass
class Decision:
    allocations: list[Allocation]
    uncovered: dict[str, float]  # product id → quantity nobody could supply
    dropped_min_order: list[str]  # suppliers dropped because their share was under their minimum order
    total: float
    reference: float  # the same quantities at the prices the suppliers first asked
    savings: float  # what the negotiation saved
    needed: float  # total quantity needed (all products, their own units)
    covered: float  # quantity bought


def effective_price(offer: Offer, s: SupplierProfile) -> float:
    """Price + a reliability penalty (2 % per missing ★, +0.5 % per 5 incidents a year): cheapest isn't always best."""
    return offer.price * (1 + 0.02 * (3 - s.reliability) + 0.005 * (s.issues_12m // 5))


def allocate(needs: list[NeedLine], offers: list[Offer], suppliers: dict[str, SupplierProfile]) -> Decision:
    def fill(excluded: set[str]) -> tuple[list[Allocation], dict[str, float]]:
        allocs, uncovered = [], {}
        for line in needs:
            left = line.need
            candidates = sorted(
                (o for o in offers if o.product_id == line.product_id and o.supplier_id not in excluded and o.qty > 0),
                key=lambda o: effective_price(o, suppliers[o.supplier_id]),
            )
            for o in candidates:
                if left <= 0:
                    break
                take = _round_qty(min(left, o.qty), line.unit)
                if take > 0:
                    allocs.append(Allocation(o.supplier_id, line.product_id, take, o.price, o.opening or o.price))
                    left = round(left - take, 3)
            if left > 0.001:
                uncovered[line.product_id] = _round_qty(left, line.unit)
        return allocs, uncovered

    excluded: set[str] = set()
    while True:  # drop suppliers whose share is under their minimum order, then re-allocate without them
        allocs, uncovered = fill(excluded)
        spend: dict[str, float] = {}
        for a in allocs:
            spend[a.supplier_id] = spend.get(a.supplier_id, 0) + a.qty * a.price
        under = {sid for sid, total in spend.items() if total < suppliers[sid].min_order}
        # only drop when someone else can take the volume, otherwise the shortage would be worse than the minimum
        under = {sid for sid in under if any(o.supplier_id != sid and o.supplier_id not in excluded for o in offers
                                              if any(a.product_id == o.product_id for a in allocs if a.supplier_id == sid))}  # fmt: skip
        if not under:
            break
        excluded |= under
    total = round(sum(a.qty * a.price for a in allocs), 2)
    reference = round(sum(a.qty * a.opening for a in allocs), 2)
    needed, covered = sum(n.need for n in needs), sum(a.qty for a in allocs)
    return Decision(allocs, uncovered, sorted(excluded), total, reference, round(reference - total, 2), round(needed, 1), round(covered, 1))
