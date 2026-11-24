"""
One buying round (« le marché du matin »): the central buyer calls every relevant supplier AT THE SAME TIME.

    MarketRound.run()
      need      GET /api/purchase-orders/needs (last year's Christmas week − stock): the basket, and who can supply what
      profiles  GET /api/suppliers/{id} + /api/context/for: lead time, minimum, ★ reliability / flexibility, persona
      calls     one asyncio task per supplier, all concurrent: ring → quote → counter with the competitors' prices
                (shared Board) → final offer → wait for the central decision → « vous l'avez » / « pas cette fois »
      decision  strategy.allocate(): cheapest reliable cover, capacities, minimum orders, shortage reported
      orders    POST /api/purchase-orders for each winner (negotiated unit prices), actor voice_agent « Agent achats »
      summary   one spoken sentence for the team

Every step is a MarketEvent appended to the round (and streamed: routers/market.py). `pace` stretches the pauses so a
human can follow 9 calls at once (1.0 = demo, 0 = tests).
"""

import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.agent.prompts import get_meta
from app.tools import ErpClient

from . import voices
from .events import MarketEvent
from .strategy import NeedLine, Offer, SupplierProfile, allocate, counter, is_fixed_price, parse_stars, supplier_terms
from .voices import eur, of, qty, short, the

MAX_COUNTERS = 2


@dataclass
class Board:
    """What the central buyer knows: every supplier's current offer per product, as the calls go."""

    offers: dict[tuple[str, str], Offer] = field(default_factory=dict)  # (supplier, product) → offer
    quoted: set[str] = field(default_factory=set)
    final: set[str] = field(default_factory=set)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def post(self, offers: list[Offer], *, first: bool = False, final: bool = False) -> None:
        async with self.changed:
            for o in offers:
                self.offers[(o.supplier_id, o.product_id)] = o
            if offers and first:
                self.quoted.add(offers[0].supplier_id)
            if offers and final:
                self.final.add(offers[0].supplier_id)
            self.changed.notify_all()

    def best_other(self, supplier_id: str, product_id: str) -> Offer | None:
        others = [o for (s, p), o in self.offers.items() if p == product_id and s != supplier_id and o.qty > 0]
        return min(others, key=lambda o: o.price, default=None)

    async def wait_for(self, suppliers: set[str], which: str, timeout: float) -> None:
        async def ready() -> None:
            async with self.changed:
                await self.changed.wait_for(lambda: suppliers <= getattr(self, which))

        try:
            await asyncio.wait_for(ready(), timeout)
        except TimeoutError:
            pass


class MarketRound:
    def __init__(self, erp: ErpClient | None = None, pace: float = 1.0, seed: str | None = None, per_category: int = 2):
        self.id = uuid.uuid4().hex[:8]
        self.erp = erp or ErpClient("voice_agent", "Agent achats")
        self.pace, self.seed, self.per_category = pace, seed or self.id, per_category
        self.events: list[MarketEvent] = []
        self.done = False
        self.updated = asyncio.Condition()
        self.started = time.perf_counter()
        self.rng = random.Random(self.seed)
        self.board = Board()
        self.decided = asyncio.Event()
        self.decision = None

    # ── events ──

    async def emit(self, type: str, call: str | None = None, **data: Any) -> None:
        ev = MarketEvent(type=type, t=int((time.perf_counter() - self.started) * 1000), call=call, data=data)
        async with self.updated:
            self.events.append(ev)
            self.updated.notify_all()

    async def pause(self, text: str = "", base: float = 0.4) -> None:
        """Time to « say » a line, so humans can follow (pace 0 in tests)."""
        if self.pace > 0:
            await asyncio.sleep(self.pace * min(3.2, base + len(text) / 32 + self.rng.uniform(0, 0.5)))

    # ── the round ──

    async def run(self) -> None:
        try:
            await self._run()
        except Exception as e:
            print(f"[market] round {self.id} failed: {type(e).__name__}: {e}", flush=True)
            await self.emit("error", message=str(e) or type(e).__name__)
        finally:
            async with self.updated:
                self.done = True
                self.updated.notify_all()

    async def _run(self) -> None:
        today = date.fromisoformat((await get_meta()).get("today") or date.today().isoformat())
        ref_from, ref_to = date(today.year - 1, 12, 21), date(today.year - 1, 12, 27)
        need_by = (date(today.year, 12, 21) - timedelta(days=3)).isoformat()
        need = await self.erp.get("/api/purchase-orders/needs", {"from": ref_from.isoformat(), "to": ref_to.isoformat(), "perCategory": self.per_category})  # fmt: skip
        lines = [
            NeedLine(l["productId"], l["name"], l["unit"], l["category"], l["cost"], l["need"], {s["supplierId"]: s["price"] for s in l["suppliers"] if "price" in s})  # fmt: skip
            for l in need["lines"]
        ]
        who_by_product = {l["productId"]: {s["supplierId"] for s in l["suppliers"]} for l in need["lines"]}
        involved = sorted({s for ids in who_by_product.values() for s in ids})
        all_suppliers = await self.erp.get("/api/suppliers", {"limit": 50})
        profiles = dict(zip(involved, await asyncio.gather(*(self.profile(sid) for sid in involved)), strict=True))

        await self.emit(
            "round_started",
            title="Semaine de Noël",
            reference=f"ventes du {ref_from.strftime('%d/%m/%Y')} au {ref_to.strftime('%d/%m/%Y')} − stock",
            needBy=need_by,
            needs=[{"productId": l.product_id, "name": short(l.name), "unit": l.unit, "category": l.category, "need": l.need, "listPrice": l.reference_price, "suppliers": sorted(who_by_product[l.product_id])} for l in lines],  # fmt: skip
            suppliers=[{"id": s["id"], "name": s["name"], "city": s.get("city"), "categories": s.get("categories"), "called": s["id"] in profiles,  # fmt: skip
                        **({"contact": profiles[s["id"]].contact, "reliability": profiles[s["id"]].reliability, "flexibility": profiles[s["id"]].flexibility} if s["id"] in profiles else {})}  # fmt: skip
                       for s in all_suppliers],
        )
        for s in all_suppliers:
            if s["id"] not in profiles:
                await self.emit("call_skipped", call=s["id"], reason="Rien à acheter dans ses familles cette semaine : stock suffisant.")

        calls = [self.call(profiles[sid], [l for l in lines if sid in who_by_product[l.product_id]], need_by, who_by_product, set(profiles)) for sid in profiles]  # fmt: skip
        decide = asyncio.create_task(self.decide(lines, profiles))
        await asyncio.gather(*calls, decide)
        await self.place_orders(lines, profiles, need_by)

    async def profile(self, supplier_id: str) -> SupplierProfile:
        s, ctx = await asyncio.gather(
            self.erp.get(f"/api/suppliers/{supplier_id}"),
            self.erp.get("/api/context/for", {"entityType": "supplier", "id": supplier_id}),
        )
        entries = {e["title"]: e["body"] for e in ctx.get("entries") or []}
        reliability, flexibility = parse_stars(entries.get("Profil", ""))
        contact = ((s.get("contacts") or [{}])[0].get("name") or "").strip()
        persona = "\n".join(entries.get(k, "") for k in ("Les personnes et leur façon de parler", "Négociation", "Ce qui les agace") if entries.get(k))  # fmt: skip
        return SupplierProfile(
            id=s["id"], name=s["name"], lead_time_days=s.get("leadTimeDays") or 1, min_order=s.get("minOrderAmount") or 0,
            reliability=reliability, flexibility=flexibility, issues_12m=(s.get("eventStats") or {}).get("issues12m") or 0,
            contact=contact, persona=persona[:1500], fixed_price=is_fixed_price(entries.get("Négociation", "")),
        )  # fmt: skip

    # ── one call ──

    async def say(self, call: str, speaker: str, text: str) -> None:
        await self.emit("line", call=call, speaker=speaker, text=text)
        await self.pause(text)

    async def call(self, s: SupplierProfile, lines: list[NeedLine], need_by: str, who_by_product: dict, called: set[str]) -> None:
        cid, first = s.id, (s.contact.split() or [s.name])[0]
        who = f"{s.contact or 'le commercial'} de {s.name}"
        terms = {l.product_id: supplier_terms(s, l, self.seed) for l in lines}
        names = {l.product_id: l for l in lines}

        await self.emit("call_ringing", call=cid)
        await self.pause(base=0.3 + self.rng.uniform(0, 1.6))
        await self.emit("call_connected", call=cid)
        await self.say(cid, "supplier", await voices.phrase(who, s.persona, "Tu décroches : salue l'agent achats de la Crèmerie des Aravis, en une phrase courte.", [], f"{s.name}, {first} à l'appareil, bonjour !"))  # fmt: skip

        ask = " ; ".join(f"{qty(l.need, l.unit)} {of(l.name)}" for l in lines)
        await self.say(cid, "buyer", f"Bonjour {first}, l'agent achats de la Crèmerie des Aravis. Pour la semaine de Noël il nous faudrait {ask}, livré avant le {date.fromisoformat(need_by).strftime('%d/%m')}. Vous me faites quel prix ?")  # fmt: skip

        offers = [Offer(cid, l.product_id, terms[l.product_id].opening, terms[l.product_id].capacity, opening=terms[l.product_id].opening) for l in lines]  # fmt: skip
        quote = " ; ".join(f"{qty(o.qty, names[o.product_id].unit)} {of(names[o.product_id].name)} à {eur(o.price)}" for o in offers)  # fmt: skip
        await self.say(cid, "supplier", await voices.phrase(who, s.persona, f"Tu donnes ton offre (ce que tu peux livrer et ton prix, J+{s.lead_time_days}) : {quote}.", [eur(o.price) for o in offers], f"Je peux te faire {quote}, livré en J+{s.lead_time_days}."))  # fmt: skip
        await self.board.post(offers, first=True)
        await self.emit("offer", call=cid, offers=[self._offer(o, terms) for o in offers], final=False)

        # wait for the competitors' first quotes on the same products, then play them against each other
        rivals = {sid for l in lines for sid in who_by_product[l.product_id] if sid in called} - {cid}
        await self.board.wait_for(rivals, "quoted", timeout=8 * max(self.pace, 0.05))
        for attempt in range(MAX_COUNTERS):
            target = max(offers, key=lambda o: o.qty * o.price)  # the biggest line is where to push
            rival = self.board.best_other(cid, target.product_id)
            product = the(names[target.product_id].name)
            if rival and rival.price < target.price:
                rival_name = await self._name(rival.supplier_id)
                await self.emit("intel", call=cid, fromCall=rival.supplier_id, productId=target.product_id, price=rival.price)
                await self.say(cid, "buyer", f"J'ai {rival_name} à {eur(rival.price)} sur {product}. Vous pouvez vous aligner ?" if attempt == 0 else f"{rival_name} est toujours à {eur(rival.price)} sur {product}. Un dernier effort ?")  # fmt: skip
            else:
                rival = None
                await self.say(cid, "buyer", f"Sur ces volumes, vous pouvez faire un geste sur {product} ?" if attempt == 0 else f"Et si on vous prend tout le volume sur {product}, vous descendez encore ?")  # fmt: skip
            new_offers, moved, finals = [], [], []
            for o in offers:
                best = self.board.best_other(cid, o.product_id) if o.product_id == target.product_id else None
                price, final = counter(terms[o.product_id], o.price, best.price if best else None)
                new_offers.append(Offer(cid, o.product_id, price, o.qty, final, opening=o.opening))
                (moved if price < o.price else finals).append((o, price))
            t_new = next(o for o in new_offers if o.product_id == target.product_id)
            if t_new.price < target.price:
                line = await voices.phrase(who, s.persona, f"Tu ACCEPTES de baisser {product} à {eur(t_new.price)} (dis clairement que tu descends)" + (", c'est ton dernier prix" if t_new.final else ""), [eur(t_new.price)], f"Allez, je descends à {eur(t_new.price)} sur {product}" + (", mais c'est mon dernier prix." if t_new.final else "."), forbid=voices.REFUSAL)  # fmt: skip
            else:
                line = await voices.phrase(who, s.persona, f"Tu refuses de baisser {product} : {eur(t_new.price)}, c'est ton dernier prix (lait d'hiver, saison).", [eur(t_new.price)], f"Non, là je ne peux pas : {eur(t_new.price)}, c'est mon dernier prix sur {product}.")  # fmt: skip
            await self.say(cid, "supplier", line)
            offers = new_offers
            final_now = all(o.final for o in offers) or t_new.price >= target.price
            await self.board.post(offers, final=final_now)
            await self.emit("offer", call=cid, offers=[self._offer(o, terms) for o in offers], final=final_now)
            if final_now:
                break
        else:
            await self.board.post(offers, final=True)
            await self.emit("offer", call=cid, offers=[self._offer(o, terms) for o in offers], final=True)

        await self.emit("call_waiting", call=cid)
        await self.decided.wait()
        won = [a for a in self.decision.allocations if a.supplier_id == cid]
        if won:
            what = " ; ".join(f"{qty(a.qty, names[a.product_id].unit)} {of(names[a.product_id].name)} à {eur(a.price)}" for a in won)  # fmt: skip
            await self.say(cid, "buyer", f"C'est bon pour nous : {what}. Je vous envoie le bon de commande tout de suite.")
            await self.say(cid, "supplier", await voices.phrase(who, s.persona, "On vient de te passer la commande : remercie et conclus en une phrase.", [], f"Parfait, merci ! Je prépare ça, bonnes fêtes à toute l'équipe."))  # fmt: skip
        else:
            await self.say(cid, "buyer", f"Merci {first}, cette fois on part ailleurs sur ces volumes. On se rappelle très vite.")
            await self.say(cid, "supplier", await voices.phrase(who, s.persona, "Tu n'as pas été retenu cette fois : réponds en une phrase, beau joueur.", [], "Dommage ! Rappelle-moi si tu manques de quelque chose."))  # fmt: skip
        await self.emit("call_ended", call=cid, won=bool(won), total=round(sum(a.qty * a.price for a in won), 2))

    async def _name(self, supplier_id: str) -> str:
        for ev in self.events:
            if ev.type == "round_started":
                return next((s["name"] for s in ev.data["suppliers"] if s["id"] == supplier_id), supplier_id)
        return supplier_id

    @staticmethod
    def _offer(o: Offer, terms: dict) -> dict:
        return {"productId": o.product_id, "price": o.price, "qty": o.qty, "final": o.final, "regular": terms[o.product_id].regular}

    # ── the central decision ──

    async def decide(self, lines: list[NeedLine], profiles: dict[str, SupplierProfile]) -> None:
        await self.board.wait_for(set(profiles), "final", timeout=60 * max(self.pace, 0.05))
        self.decision = allocate(lines, list(self.board.offers.values()), profiles)
        d = self.decision
        await self.emit(
            "decision",
            allocations=[{"supplierId": a.supplier_id, "productId": a.product_id, "qty": a.qty, "price": a.price} for a in d.allocations],  # fmt: skip
            uncovered=d.uncovered, droppedMinOrder=d.dropped_min_order, total=d.total, reference=d.reference, savings=d.savings,
            needed=d.needed, covered=d.covered,
        )  # fmt: skip
        self.decided.set()

    async def place_orders(self, lines: list[NeedLine], profiles: dict[str, SupplierProfile], need_by: str) -> None:
        d = self.decision
        by_supplier: dict[str, list] = {}
        for a in d.allocations:
            by_supplier.setdefault(a.supplier_id, []).append(a)

        async def place(sid: str, allocs: list) -> None:
            body = {"supplierId": sid, "expectedDate": need_by, "note": "Marché du matin, semaine de Noël : prix négociés par l'agent achats",  # fmt: skip
                    "lines": [{"productId": a.product_id, "qty": a.qty, "unitPrice": a.price} for a in allocs]}  # fmt: skip
            try:
                po = await self.erp.post("/api/purchase-orders", body)
                await self.emit("po_created", call=sid, poId=po["id"], number=po.get("number"), total=po.get("totalHt"))
            except Exception as e:
                await self.emit("error", call=sid, message=f"Bon de commande {profiles[sid].name} : {e}")

        await asyncio.gather(*(place(sid, allocs) for sid, allocs in by_supplier.items()))
        by_id = {l.product_id: l for l in lines}
        pct = round(100 * d.savings / d.reference, 1) if d.reference else 0
        # what the usual supplier alone would have covered: the reason to call everyone at Christmas
        regular = sum(min(l.need, supplier_terms(profiles[sid], l, self.seed).capacity) for l in lines for sid in l.list_prices if sid in profiles)  # fmt: skip
        coverage = int(100 * d.covered / d.needed) if d.needed else 0  # rounded DOWN: never « 100 % » with a shortage
        alone = int(100 * min(regular, d.needed) / d.needed) if d.needed else 0
        text = (f"Marché bouclé : {len(by_supplier)} fournisseurs retenus sur {len(profiles)} appelés, {eur(d.total)} au total. "
                f"La négociation a fait gagner {eur(d.savings)} ({str(pct).replace('.', ',')} %) sur les prix demandés, "
                f"et le besoin de Noël est couvert à {coverage} % contre {alone} % avec nos seuls fournisseurs habituels.")  # fmt: skip
        if d.uncovered:
            text += " Il manque encore " + ", ".join(f"{qty(q, by_id[p].unit)} {of(by_id[p].name)}" for p, q in d.uncovered.items()) + " : à rationner ou à chercher ailleurs."  # fmt: skip
        await self.emit("summary", text=text, total=d.total, reference=d.reference, savings=d.savings, savingsPct=pct, suppliers=len(by_supplier), called=len(profiles), coverage=coverage, coverageRegular=alone)  # fmt: skip


# ── registry (in memory: the last rounds, for the page and late viewers) ──

ROUNDS: dict[str, MarketRound] = {}


def start_round(**kwargs: Any) -> MarketRound:
    r = MarketRound(**kwargs)
    ROUNDS[r.id] = r
    for old in list(ROUNDS)[:-5]:
        ROUNDS.pop(old, None)
    asyncio.get_running_loop().create_task(r.run())
    return r
