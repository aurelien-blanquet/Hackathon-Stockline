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
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from app.agent.prompts import get_meta
from app.config import env
from app.tools import ErpClient

from . import voices
from .events import MarketEvent
from . import levers
from .levers import LABELS, buyer_line
from .strategy import Lot, NeedLine, Offer, SupplierProfile, economic_lot, is_fixed_price, parse_stars, supplier_terms
from .voices import eur, of, qty, short, the

MAX_COUNTERS = 2
LINE_WAIT_S = 2.5  # demo pace: how long a prepared model line may still take when its turn comes (then: template)
FAST_LINE_WAIT_S = 1.5  # fast mode
REPLENISH_DAYS = int(env("REPLENISH_DAYS", "28"))  # sales window averaged by the morning replenishment
REPLENISH_COVER_DAYS = float(env("REPLENISH_COVER_DAYS", "7"))  # every product held to ≥ this many days of average sales
REPLENISH_LEAD_DAYS = int(env("REPLENISH_LEAD_DAYS", "2"))  # delivered within (producers slower than that are not called)
REPLENISH_MAX_COVER_DAYS = float(env("REPLENISH_MAX_COVER_DAYS", "42"))  # economic lot: at most 6 weeks (shelf life permitting)


def _days(n: float) -> str:
    return "une semaine" if n == 7 else f"{n:g} jours"


MARKET_NOTE = "Marché du matin"  # purchase-order note prefix: a new round replaces the drafts of the previous one


async def fetch_profile(erp: ErpClient, supplier_id: str) -> SupplierProfile:
    """A supplier as the buyer sees it: ERP card + supplier sheet (★ reliability / flexibility, persona, fixed price)."""
    s, ctx = await asyncio.gather(
        erp.get(f"/api/suppliers/{supplier_id}"),
        erp.get("/api/context/for", {"entityType": "supplier", "id": supplier_id}),
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


def arrival(today: date, s: SupplierProfile) -> date:
    """When this supplier's goods reach us if ordered today."""
    return today + timedelta(days=max(0, s.lead_time_days))


class MarketRound:
    def __init__(
        self,
        erp: ErpClient | None = None,
        pace: float = 1.0,
        seed: str | None = None,
        per_category: int = 2,
        mode: str = "christmas",
        trigger: str = "manuel",
    ):
        self.id = uuid.uuid4().hex[:8]
        self.erp = erp or ErpClient("voice_agent", "Agent achats")
        self.pace, self.seed, self.per_category = pace, seed or self.id, per_category
        self.mode = mode  # « daily »: the morning replenishment (every product ≥ an average of its sales); « christmas »
        self.trigger = trigger  # « automatique (chaque matin à 06:00) » or « manuel »
        self.events: list[MarketEvent] = []
        self.done = False
        self.updated = asyncio.Condition()
        self.started = time.perf_counter()
        self.rng = random.Random(self.seed)
        self.decided = asyncio.Event()
        self.decision = None
        self.orders: dict[str, asyncio.Future] = {}  # winning supplier → its purchase order (None if the write failed)
        self.metrics: dict[str, Any] = {"pace": pace}
        self.calls_total = self.told = 0
        self.skipped_products: list[dict] = []  # out of season / vintage: not bought this morning
        self.lots: dict[str, Lot] = {}  # daily: product → its economic lot (how much beyond the one-week reorder point)
        # the morning it ran (wall clock, not meta.today: the schedule buys once per REAL morning; needs and dates
        # still come from the business date) — written in the PO note, read back by schedule.done_today
        self.run_day = date.today().isoformat()  # noqa: DTZ011

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
        if self.mode == "daily":  # every product back to at least an average of its sales (backend: replenishment_needs)
            need_by = (today + timedelta(days=REPLENISH_LEAD_DAYS)).isoformat()
            need = await self.erp.get("/api/purchase-orders/replenishment", {"days": REPLENISH_DAYS, "coverDays": REPLENISH_COVER_DAYS})
            title = "Réassort du matin"
            reference = (f"{need['checked']} produits vérifiés, {need['below']} sous {_days(REPLENISH_COVER_DAYS)} de ventes moyennes "
                         f"(moyenne des {REPLENISH_DAYS} derniers jours) · {self.trigger}")  # fmt: skip
            need["lines"] = await self.without_blocked(need["lines"])
        else:
            ref_from, ref_to = date(today.year - 1, 12, 21), date(today.year - 1, 12, 27)
            need_by = (date(today.year, 12, 21) - timedelta(days=3)).isoformat()
            need = await self.erp.get("/api/purchase-orders/needs", {"from": ref_from.isoformat(), "to": ref_to.isoformat(), "perCategory": self.per_category})  # fmt: skip
            title, reference = "Semaine de Noël", f"ventes du {ref_from.strftime('%d/%m/%Y')} au {ref_to.strftime('%d/%m/%Y')} − stock"
        self.need_by = need_by
        lines = [
            NeedLine(l["productId"], l["name"], l["unit"], l["category"], l["cost"], l["need"], {s["supplierId"]: s["price"] for s in l["suppliers"] if "price" in s})  # fmt: skip
            for l in need["lines"]
        ]
        who_by_product = {l["productId"]: {s["supplierId"] for s in l["suppliers"]} for l in need["lines"]}
        involved = sorted({s for ids in who_by_product.values() for s in ids})
        all_suppliers = await self.erp.get("/api/suppliers", {"limit": 50})
        if not lines:  # every product already holds its average: nobody to call this morning
            await self.emit("round_started", title=title, reference=reference, mode=self.mode, skippedProducts=self.skipped_products,
                            needBy=need_by, needs=[], suppliers=[{"id": s["id"], "name": s["name"], "city": s.get("city"), "categories": s.get("categories"), "called": False} for s in all_suppliers])  # fmt: skip
            await self.emit("summary", text="Rien à acheter ce matin : chaque produit tient au moins sa moyenne de ventes.", total=0, reference=0,
                            savings=0, savingsPct=0, suppliers=0, called=0, coverage=100, coverageRegular=100, metrics=self.metrics)  # fmt: skip
            return
        profiles = dict(zip(involved, await asyncio.gather(*(self.profile(sid) for sid in involved)), strict=True))
        # a supplier who cannot deliver before the need date is not called (its lead time is in the ERP)
        too_slow = {sid: p for sid, p in profiles.items() if arrival(today, p) > date.fromisoformat(need_by)}
        for sid in too_slow:
            profiles.pop(sid)
        if self.mode == "daily":  # under one week → reordered; how much: the economic lot (strategy.economic_lot)
            lines = self.economic_lots(lines, need["lines"], profiles)

        await self.emit(
            "round_started",
            title=title,
            reference=reference,
            mode=self.mode,
            skippedProducts=self.skipped_products,
            needBy=need_by,
            needs=[{**self.need_view(l), "suppliers": sorted(who_by_product[l.product_id])} for l in lines],
            lotSaved=round(sum(x.saved for x in self.lots.values()), 2),
            suppliers=[{"id": s["id"], "name": s["name"], "city": s.get("city"), "categories": s.get("categories"), "called": s["id"] in profiles,  # fmt: skip
                        **({"contact": profiles[s["id"]].contact, "reliability": profiles[s["id"]].reliability, "flexibility": profiles[s["id"]].flexibility} if s["id"] in profiles else {})}  # fmt: skip
                       for s in all_suppliers],
        )
        for s in all_suppliers:
            if s["id"] in too_slow:
                await self.emit("call_skipped", call=s["id"], reason=f"Délai trop long : livrerait le {arrival(today, too_slow[s['id']]).strftime('%d/%m')}, après le {date.fromisoformat(need_by).strftime('%d/%m')}.")  # fmt: skip
            elif s["id"] not in profiles:
                when = "ce matin" if self.mode == "daily" else "cette semaine"
                await self.emit("call_skipped", call=s["id"], reason=f"Rien à acheter dans ses familles {when} : stock suffisant.")

        # 1. the whole negotiation, in code (synchronized rounds: everyone answers the same snapshot) — milliseconds
        from .express import negotiate  # express imports this module

        offered = {sid: {pid for pid, ids in who_by_product.items() if sid in ids} for sid in profiles}
        script = negotiate(lines, profiles, self.seed, offered=offered, synchronized=True, memory=levers.MEMORY)
        levers.MEMORY.learn(script)  # market/levers.py: which argument moved which producer, for the next round
        self.decision = script.decision
        self.metrics["timeToDecisionMs"] = self.ms()
        self.metrics["exchanges"] = sum(len(st) for st in script.steps.values())
        terms = {sid: {l.product_id: supplier_terms(p, l, self.seed) for l in lines if l.product_id in offered[sid]} for sid, p in profiles.items()}  # fmt: skip

        # 2. purchase orders now, in parallel with the narration (announced per supplier only once written)
        loop = asyncio.get_running_loop()
        self.orders = {sid: loop.create_future() for sid in {a.supplier_id for a in self.decision.allocations}}
        orders = asyncio.create_task(self.write_orders(profiles, need_by))

        # 3. the narration: one task per call, all at once, telling the script
        voices.reset_stats()
        names = {l.product_id: l for l in lines}
        self.calls_total, self.told = len(profiles), 0
        if not profiles:
            await self.announce_decision()
        await asyncio.gather(*(self.tell(p, script.steps[sid], names, need_by, terms) for sid, p in profiles.items()))
        await orders
        await self.summarize(lines, profiles)

    def economic_lots(self, lines: list[NeedLine], raw: list[dict], profiles: dict[str, SupplierProfile]) -> list[NeedLine]:
        """Each short product: the lot that costs least per unit sold (volume tier vs storage, within half its shelf
        life). The producers then quote that lot against a one-week lot (ref_qty): the same volume tier, negotiated."""
        by_id = {l["productId"]: l for l in raw}
        out = []
        for line in lines:
            l = by_id[line.product_id]
            sellers = [x for x in l["suppliers"] if x["supplierId"] in profiles]
            lot = economic_lot(
                l.get("avgPerDay") or 0.001, (l.get("available") or 0) + (l.get("incoming") or 0), line.unit, line.reference_price,
                l.get("shelfLifeDays"), min((x.get("paymentTermsDays") or 30 for x in sellers), default=30),
                floor_days=round(REPLENISH_COVER_DAYS), max_days=REPLENISH_MAX_COVER_DAYS,
                discount=any(not profiles[x["supplierId"]].fixed_price for x in sellers),
            )  # fmt: skip
            self.lots[line.product_id] = lot
            out.append(replace(line, need=lot.qty, ref_qty=lot.week_qty if lot.qty > lot.week_qty else None))
        return out

    def need_view(self, l: NeedLine) -> dict:
        view = {"productId": l.product_id, "name": short(l.name), "unit": l.unit, "category": l.category, "need": l.need, "listPrice": l.reference_price}  # fmt: skip
        lot = self.lots.get(l.product_id)
        if not lot:
            return view
        return view | {"weekNeed": lot.week_qty, "coverDays": lot.cover_days, "limitDays": lot.limit_days, "shelfLifeDays": lot.shelf_days,
                "discountPct": round(100 * lot.discount, 1), "holdingPct": round(100 * lot.holding, 2), "lotSaved": lot.saved}  # fmt: skip

    async def without_blocked(self, lines: list[dict]) -> list[dict]:
        """A product whose whole trade is out (season, vintage: its ERP sheet says « ne sort pas avant… ») is not
        bought: said on the page, then left out (express.supply_blocked reads the same sheet)."""
        from .express import supply_blocked  # express imports this module

        contexts = await asyncio.gather(*(self.erp.get("/api/context/for", {"entityType": "product", "id": l["productId"]}) for l in lines),
                                        return_exceptions=True)  # fmt: skip
        kept = []
        for l, ctx in zip(lines, contexts, strict=True):
            blocked = supply_blocked(ctx) if not isinstance(ctx, BaseException) else None
            if blocked:
                self.skipped_products.append({"productId": l["productId"], "name": short(l["name"]), "reason": blocked[0]})
            else:
                kept.append(l)
        return kept

    async def profile(self, supplier_id: str) -> SupplierProfile:
        return await fetch_profile(self.erp, supplier_id)

    # ── the narration: the script, told call by call (never decides anything) ──

    async def say(self, call: str | None, speaker: str, text: str) -> None:
        await self.emit("line", call=call, speaker=speaker, text=text)
        await self.pause(text)

    async def line(self, task: asyncio.Task, fallback: str) -> str:
        """A phrase prepared in parallel since the call started: its text if ready in time, else the template."""
        try:
            return await asyncio.wait_for(asyncio.shield(task), LINE_WAIT_S if self.pace > 0 else FAST_LINE_WAIT_S)
        except Exception:  # late or failed: the template says the same numbers
            voices.STATS.fallbacks += 1
            return fallback

    async def tell(self, s: SupplierProfile, steps: list, names: dict, need_by: str, terms: dict) -> None:
        """One call, from the script: ring → greeting → request → quote → counters → wait for the decision → close."""
        cid, first = s.id, (s.contact.split() or [s.name])[0]
        who = f"{s.contact or 'le commercial'} de {s.name}"
        mine = [names[pid] for pid in sorted({o.product_id for st in steps for o in st.offers})]

        # every model line of this call is asked for NOW, in parallel: the narration then only reads them
        quote, prepared = steps[0].offers if steps else [], []
        q_text = " ; ".join(f"{qty(o.qty, names[o.product_id].unit)} {of(names[o.product_id].name)} à {eur(o.price)}" for o in quote)  # fmt: skip
        fixed = bool(quote) and all(o.final for o in quote)
        q_fallback = f"Je peux te faire {q_text}, livré en J+{s.lead_time_days}." + (" Et c'est mon prix, il est fixe." if fixed else "")  # fmt: skip
        prepared.append((asyncio.create_task(voices.phrase(who, s.persona, f"Tu donnes ton offre (ce que tu peux livrer et ton prix, J+{s.lead_time_days}) : {q_text}." + (" Ton prix est fixe, tu le dis." if fixed else ""), [eur(o.price) for o in quote], q_fallback)), q_fallback))  # fmt: skip
        for st in steps[1:]:
            product = the(names[st.target].name)
            if st.after < st.before:
                fb = f"Allez, je descends à {eur(st.after)} sur {product}" + (", mais c'est mon dernier prix." if all(o.final for o in st.offers) else ".")  # fmt: skip
                why = f", en échange de ce que propose l'acheteur ({LABELS[st.lever]})" if st.lever and st.lever != "concurrence" else ""
                task = voices.phrase(who, s.persona, f"Tu ACCEPTES de baisser {product} à {eur(st.after)}{why} (dis clairement que tu descends)", [eur(st.after)], fb, forbid=voices.REFUSAL)  # fmt: skip
            else:
                fb = f"Non, là je ne peux pas : {eur(st.after)}, c'est mon dernier prix sur {product}."
                task = voices.phrase(who, s.persona, f"Tu refuses de baisser {product} : {eur(st.after)}, c'est ton dernier prix (lait d'hiver, saison).", [eur(st.after)], fb)  # fmt: skip
            prepared.append((asyncio.create_task(task), fb))

        await self.emit("call_ringing", call=cid)
        await self.pause(base=0.3 + self.rng.uniform(0, 1.6))
        await self.emit("call_connected", call=cid)
        await self.say(cid, "supplier", voices.greeting(first, s.name, s.persona, self.rng))
        ask = " ; ".join(f"{qty(l.need, l.unit)} {of(l.name)}" for l in mine)
        why = "Pour notre réassort" if self.mode == "daily" else "Pour la semaine de Noël"
        await self.say(cid, "buyer", f"Bonjour {first}, l'agent achats de la Crèmerie des Aravis. {why} il nous faudrait {ask}, livré avant le {date.fromisoformat(need_by).strftime('%d/%m')}. Vous me faites quel prix ?")  # fmt: skip
        for i, st in enumerate(steps):
            task, fallback = prepared[i]
            if st.kind == "quote":
                await self.say(cid, "supplier", await self.line(task, fallback))
                await self.emit("offer", call=cid, offers=[self._offer(o, terms[cid]) for o in st.offers], final=all(o.final for o in st.offers))  # fmt: skip
                continue
            product = the(names[st.target].name)
            if st.rival:  # the competitor's PRICE is an argument, its name stays confidential (METIER.md: « le prix du concurrent »)
                await self.emit("intel", call=cid, fromCall=st.rival.supplier_id, productId=st.target, price=st.rival.price)
            if st.lever:  # market/levers.py: the argument this producer responds to, learned over the previous rounds
                await self.emit("lever", call=cid, lever=st.lever, label=LABELS[st.lever], productId=st.target)
            await self.say(cid, "buyer", buyer_line(st.lever, product, eur(st.rival.price) if st.rival else None, i == 1))
            await self.say(cid, "supplier", await self.line(task, fallback))
            await self.emit("offer", call=cid, offers=[self._offer(o, terms[cid]) for o in st.offers], final=st is steps[-1])
        await self.emit("call_waiting", call=cid)
        self.told += 1
        if self.told == self.calls_total:
            await self.announce_decision()
        await self.decided.wait()

        won = [a for a in self.decision.allocations if a.supplier_id == cid]
        if won:
            po = await self.orders[cid]  # never « bon de commande envoyé » before the ERP said yes
            what = " ; ".join(f"{qty(a.qty, names[a.product_id].unit)} {of(names[a.product_id].name)} à {eur(a.price)}" for a in won)  # fmt: skip
            if po is not None:
                await self.say(cid, "buyer", f"C'est bon pour nous : {what}. Le bon de commande {po.get('number') or ''} vient de partir.".replace("  ", " "))  # fmt: skip
                await self.emit("po_created", call=cid, poId=po["id"], number=po.get("number"), total=po.get("totalHt"))
            else:
                await self.say(cid, "buyer", f"C'est bon pour nous : {what}. Je vous confirme le bon de commande par écrit dans la journée.")  # fmt: skip
            await self.say(cid, "supplier", voices.thanks(first, s.persona, True, self.rng))
        else:
            await self.say(cid, "buyer", f"Merci {first}, cette fois on part ailleurs sur ces volumes. On se rappelle très vite.")
            await self.say(cid, "supplier", voices.thanks(first, s.persona, False, self.rng))
        await self.emit("call_ended", call=cid, won=bool(won), total=round(sum(a.qty * a.price for a in won), 2))

    @staticmethod
    def _offer(o: Offer, terms: dict) -> dict:
        return {"productId": o.product_id, "price": o.price, "qty": o.qty, "final": o.final, "regular": terms[o.product_id].regular}

    async def announce_decision(self) -> None:
        """Shown once every call has told its final offer (the decision itself was taken in code at the start)."""
        d = self.decision
        await self.emit(
            "decision",
            allocations=[{"supplierId": a.supplier_id, "productId": a.product_id, "qty": a.qty, "price": a.price} for a in d.allocations],  # fmt: skip
            uncovered=d.uncovered, droppedMinOrder=d.dropped_min_order, total=d.total, reference=d.reference, savings=d.savings,
            needed=d.needed, covered=d.covered,
        )  # fmt: skip
        self.decided.set()

    # ── purchase orders: written as soon as the decision is taken, in parallel with the narration ──

    async def write_orders(self, profiles: dict[str, SupplierProfile], need_by: str) -> None:
        """One purchase order per winning supplier, once. Each winner's future resolves to its PO (or None on failure)."""
        by_supplier: dict[str, list] = {}
        for a in self.decision.allocations:
            by_supplier.setdefault(a.supplier_id, []).append(a)
        await self.cancel_previous_drafts(need_by)

        async def place(sid: str, allocs: list) -> None:
            what = f"réassort du {self.run_day}" if self.mode == "daily" else "semaine de Noël"
            body = {"supplierId": sid, "expectedDate": need_by, "note": f"{MARKET_NOTE}, {what} : prix négociés par l'agent achats",  # fmt: skip
                    "lines": [{"productId": a.product_id, "qty": a.qty, "unitPrice": a.price} for a in allocs]}  # fmt: skip
            try:
                self.orders[sid].set_result(await self.erp.post("/api/purchase-orders", body))
            except Exception as e:  # partial failure: that supplier only, said in the summary
                await self.emit("error", call=sid, message=f"Bon de commande {profiles[sid].name} : {e}")
                self.orders[sid].set_result(None)

        await asyncio.gather(*(place(sid, allocs) for sid, allocs in by_supplier.items()))
        self.metrics["timeToOrdersCreatedMs"] = self.ms()

    def ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    async def summarize(self, lines: list[NeedLine], profiles: dict[str, SupplierProfile]) -> None:
        d = self.decision
        placed = [sid for sid, f in self.orders.items() if f.done() and f.result() is not None]
        failed = [profiles[sid].name for sid, f in self.orders.items() if not (f.done() and f.result() is not None)]
        by_id = {l.product_id: l for l in lines}
        pct = round(100 * d.savings / d.reference, 1) if d.reference else 0
        # what the usual supplier alone would have covered: the reason to call everyone at Christmas
        regular = sum(min(l.need, supplier_terms(profiles[sid], l, self.seed).capacity) for l in lines for sid in l.list_prices if sid in profiles)  # fmt: skip
        coverage = int(100 * d.covered / d.needed) if d.needed else 0  # rounded DOWN: never « 100 % » with a shortage
        alone = int(100 * min(regular, d.needed) / d.needed) if d.needed else 0
        short = d.uncovered
        if self.mode == "daily" and self.lots:  # the need is the one-week floor; the rest of a lot is a choice, not a shortage
            week = {p: x.week_qty for p, x in self.lots.items() if p in by_id}
            got = {p: by_id[p].need - d.uncovered.get(p, 0) for p in week}
            cap = {p: sum(supplier_terms(profiles[sid], by_id[p], self.seed).capacity for sid in by_id[p].list_prices if sid in profiles) for p in week}  # fmt: skip
            total_week = sum(week.values())
            coverage = int(100 * sum(min(got[p], w) for p, w in week.items()) / total_week) if total_week else 100
            alone = int(100 * sum(min(cap[p], w) for p, w in week.items()) / total_week) if total_week else 100
            short = {p: round(w - got[p], 3) for p, w in week.items() if got[p] < w - 1e-9}
            lot_saved = sum(x.saved for x in self.lots.values())
            text = (f"Marché bouclé : {len(placed)} fournisseurs retenus sur {len(profiles)} appelés, {eur(d.total)} au total. "
                    f"La négociation a fait gagner {eur(d.savings)} ({str(pct).replace('.', ',')} %) sur les prix demandés"
                    + (f", et acheter en lots économiques plutôt que semaine par semaine environ {eur(lot_saved)} de plus" if lot_saved >= 1 else "")
                    + f". Chaque produit tient sa semaine de ventes à {coverage} %, contre {alone} % avec nos seuls fournisseurs habituels.")  # fmt: skip
        else:
            text = (f"Marché bouclé : {len(placed)} fournisseurs retenus sur {len(profiles)} appelés, {eur(d.total)} au total. "
                    f"La négociation a fait gagner {eur(d.savings)} ({str(pct).replace('.', ',')} %) sur les prix demandés, "
                    f"et le besoin de Noël est couvert à {coverage} % contre {alone} % avec nos seuls fournisseurs habituels.")  # fmt: skip
        if failed:
            text += f" Bon de commande non passé chez {', '.join(failed)} : à refaire à la main."
        if short:
            text += " Il manque encore " + ", ".join(f"{qty(q, by_id[p].unit)} {of(by_id[p].name)}" for p, q in short.items()) + " : à rationner ou à chercher ailleurs."  # fmt: skip
        self.metrics["timeToAllDialoguesFinishedMs"] = self.ms()
        self.metrics["voices"] = voices.STATS.snapshot()
        await self.emit("summary", text=text, total=d.total, reference=d.reference, savings=d.savings, savingsPct=pct, suppliers=len(placed),
                        called=len(profiles), coverage=coverage, coverageRegular=alone, metrics=self.metrics,
                        lotSaved=round(sum(x.saved for x in self.lots.values()), 2))  # fmt: skip

    async def cancel_previous_drafts(self, need_by: str) -> None:
        """Run the market twice → the second round's orders replace the first one's, instead of doubling them. Only
        drafts (never sent orders) written by a market round for the same date are cancelled."""
        try:  # a replenishment replaces every unsent replenishment draft (its need is recomputed from today's stock)
            query = {"status": "draft", "limit": 200} if self.mode == "daily" else {"status": "draft", "date": need_by, "limit": 200}
            drafts = await self.erp.get("/api/purchase-orders", query)
        except Exception as e:  # noqa: BLE001 — never block the round on this
            print(f"[market] previous drafts not checked: {e}", flush=True)
            return
        prefix = f"{MARKET_NOTE}, réassort" if self.mode == "daily" else MARKET_NOTE
        mine = [po for po in drafts if str(po.get("note") or "").startswith(prefix)
                and (self.mode == "daily" or ", réassort" not in str(po.get("note")))]  # fmt: skip
        results = await asyncio.gather(*(self.erp.post(f"/api/purchase-orders/{po['id']}/cancel", {}) for po in mine), return_exceptions=True)  # fmt: skip
        cancelled = [po.get("number") or po["id"] for po, r in zip(mine, results, strict=True) if not isinstance(r, Exception)]
        if cancelled:
            await self.emit("line", call=None, speaker="buyer", text=f"Brouillons du marché précédent annulés : {', '.join(cancelled)}.")


# ── registry (in memory: the last rounds, for the page and late viewers) ──

ROUNDS: dict[str, MarketRound] = {}


def start_round(**kwargs: Any) -> MarketRound:
    r = MarketRound(**kwargs)
    ROUNDS[r.id] = r
    for old in list(ROUNDS)[:-5]:
        ROUNDS.pop(old, None)
    asyncio.get_running_loop().create_task(r.run())
    return r
