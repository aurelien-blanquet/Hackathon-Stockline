"""
The numbers of the market, in code: no model decides a price, a quantity or who wins. The agents only SAY them.

    SupplierProfile    from the ERP: lead time, minimum order, reliability ★ and flexibility ★ (supplier sheet), incidents
    supplier_terms()   what one supplier can do on one product: opening price, floor (never below), capacity
    counter()          the supplier's answer to « X me fait Y, vous pouvez faire mieux ? »
    allocate()         the central decision: cheapest cover per product, penalised by unreliability, within
                       capacities, then minimum orders; what stays uncovered is reported, never hidden
"""

import hashlib
import math
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
    ref_qty: float | None = None  # a pooled purchase (market/pool.py): the size of ONE customer's lot, for the volume tier

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


VOLUME_STEP = 0.015  # price drop per doubling of the lot (a grouped purchase: one delivery instead of several)
VOLUME_MAX = 0.05


def volume_tier(line: NeedLine) -> float:
    """How much cheaper a producer quotes a lot `need` built from several customers' lots of `ref_qty`: 1,5 % per
    doubling, at most 5 %. 0 for a single customer's lot (ref_qty unset) — every negotiation before pooling."""
    if not line.ref_qty or line.need <= line.ref_qty:
        return 0.0
    return min(VOLUME_MAX, VOLUME_STEP * math.log2(line.need / line.ref_qty))


# ── the economic lot (daily replenishment) ──
# A product is reordered when it falls under one week of average sales (the reorder point). How MUCH to buy then is a
# different question: a bigger lot is cheaper per unit (the producer's volume tier above: 1,5 % per doubling of a
# normal weekly lot, ≤ 5 %, nothing from a « prix fixe » producer; and one order line fewer to receive and book), but
# it waits longer in the cold room (storage, shrink, and the money once the producer is paid) and it must be sold while
# the customer still gets half its shelf life. So: try lots of 1 to 6 weeks, keep the cheapest per unit SOLD.

LOT_COVERS = (7, 10, 14, 21, 28, 35, 42)  # stock after delivery, in days of average sales
LOT_SELL_WITHIN = 0.5  # sold before half its shelf life is gone (a customer wants the rest)
LOT_STORE_RATE = 0.12  # per year, of the price: cold room, handling, shrink
LOT_CAPITAL_RATE = 0.08  # per year, of the price: money tied up — only once the producer is paid (30–45 days)
LOT_LINE_COST = 2.0  # € per order line: receiving, checking, putting away, booking the invoice line


@dataclass
class Lot:
    cover_days: int  # stock after delivery, in days of average sales
    qty: float
    discount: float  # volume tier against a one-week lot
    holding: float  # storage + money, as a share of the price
    cost: float  # all-in cost per unit sold
    week_qty: float  # what the one-week lot would have been
    week_cost: float
    limit_days: float  # longest cover the shelf life (and the cap) allows
    shelf_days: float | None = None

    @property
    def saved(self) -> float:
        """€ saved on this lot against buying it week by week."""
        return round(max(0.0, self.week_cost - self.cost) * self.qty, 2)


def _ceil_qty(qty: float, unit: str) -> float:
    return math.ceil(qty * 2 - 1e-9) / 2 if unit in ("kg", "liter") else float(math.ceil(qty - 1e-9))


def economic_lot(avg: float, have: float, unit: str, price: float, shelf_days: float | None, pay_days: float = 30,
                 *, floor_days: int = 7, max_days: float = 42, discount: bool = True) -> Lot:  # fmt: skip
    """The quantity to buy for a product sold `avg`/day with `have` in stock (+ sent orders), at `price`."""
    week = avg * floor_days
    limit = max(floor_days, min(max_days, (shelf_days or 10_000) * LOT_SELL_WITHIN))
    lots: list[Lot] = []
    for c in (floor_days, *(c for c in LOT_COVERS if floor_days < c <= limit)):
        qty = _ceil_qty(avg * c - have, unit)
        if qty <= 0:
            continue
        tier = min(VOLUME_MAX, VOLUME_STEP * math.log2(qty / week)) if discount and qty > week else 0.0
        wait = have / avg + qty / (2 * avg)  # FIFO: today's stock goes first, then the lot sells over qty/avg days
        holding = (LOT_STORE_RATE * wait + LOT_CAPITAL_RATE * max(0.0, wait - pay_days)) / 365
        cost = price * (1 - tier) * (1 + holding) + LOT_LINE_COST / qty
        lots.append(Lot(c, qty, tier, holding, cost, 0, 0, limit, shelf_days))
    first = lots[0]
    best = min(lots, key=lambda x: x.cost - 1e-9 * x.cover_days)  # a tie keeps the smaller lot
    best.week_qty, best.week_cost = first.qty, first.cost
    return best


def supplier_terms(s: SupplierProfile, line: NeedLine, seed: str = "") -> Terms:
    r = _unit(f"{seed}|{s.id}|{line.product_id}")
    regular = s.id in line.list_prices
    ref = line.list_prices.get(s.id) or round(line.cost * (1.05 + 0.06 * r), 2)  # not their usual product: dearer
    opening = round(ref * (1.02 + 0.03 * r), 2)  # they always ask a little above their list
    floor = round(ref * (1 - {1: 0.01, 2: 0.03, 3: 0.06}.get(s.flexibility, 0.03)), 2)
    if (tier := volume_tier(line)) and not s.fixed_price:  # one bigger lot (one truck, one pick): a lower price
        opening, floor = round(opening * (1 - tier), 2), round(floor * (1 - tier), 2)
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


def counter_lever(terms: Terms, current: float, sensitivity: float, rival: float | None = None) -> tuple[float, bool, float]:
    """The supplier's answer to a lever (market/levers.py) it is `sensitivity` (0–1) responsive to: a lever that works
    moves the price more than the usual gesture AND lowers the floor. With a rival price (lever « concurrence »), it
    matches the rival down to that lower floor. Returns (price, final, new floor)."""
    from .levers import FLOOR_EXTRA, MAX_EXTRA

    floor = round(terms.floor * (1 - FLOOR_EXTRA * sensitivity), 2)
    if terms.opening <= terms.floor + 0.005:  # fixed price: nothing moves it
        return current, True, terms.floor
    target = rival - 0.01 if rival is not None and rival < current else current * (1 - 0.005 - MAX_EXTRA * sensitivity)
    price = round(max(floor, min(current, target)), 2)
    return price, price <= floor + 0.005, floor


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
        # never let minimum orders make the shortage worse: if dropping them uncovers more, keep them (the cascade
        # « everyone is under their minimum, someone else could take it » used to drop every supplier)
        _, uncovered_without = fill(excluded | under)
        if sum(uncovered_without.values()) > sum(uncovered.values()) + 1e-9:
            break
        excluded |= under
    total = round(sum(a.qty * a.price for a in allocs), 2)
    reference = round(sum(a.qty * a.opening for a in allocs), 2)
    needed, covered = sum(n.need for n in needs), sum(a.qty for a in allocs)
    return Decision(allocs, uncovered, sorted(excluded), total, reference, round(reference - total, 2), round(needed, 1), round(covered, 1))
