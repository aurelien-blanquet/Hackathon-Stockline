"""
Volume discount on a big order (« Fais-moi un prix pour 2 000 reblochons »). The ERP decides what may be offered
(backend services/discounts.py: up to 5 %, never below cost + margin, nothing for a blocked or late-paying client);
the model only proposes it and, after the caller's yes, applies it. It can never apply more than the ERP allows.
"""

from pydantic import Field

from .erp import enc
from .orders import written
from .registry import ToolContext, tool

PER = {"kg": "kilo", "piece": "pièce", "liter": "litre", "box": "carton", "dozen": "douzaine"}


async def _offer(ctx: ToolContext, client_id: str, product_id: str, qty: float, requested_pct: float | None,
                 negotiated_cost: float | None = None) -> dict:
    q = {"clientId": client_id, "productId": product_id, "qty": qty, **({"requestedPct": requested_pct} if requested_pct else {}),
         **({"negotiatedCost": round(negotiated_cost, 4)} if negotiated_cost else {})}
    return await ctx.erp.get("/api/prices/volume-offer", q)


@tool
async def propose_volume_discount(
    ctx: ToolContext,
    client_id: str = Field(description="Le client (cli_…)"),
    product_id: str = Field(description="Le produit (prd_…)"),
    qty: float = Field(description="Quantité de la ligne, dans l'unité du produit"),
    unit: str | None = Field(None, description="Unité du produit (kg, piece…), pour la phrase"),
    requested_pct: float | None = Field(None, description="Remise demandée par l'appelant, en %, s'il en a cité une"),
    delivery_date: str | None = Field(None, description="Jour de livraison voulu (AAAA-MM-JJ), si dit"),
) -> dict:
    """
    Grosse commande, prix jugé trop cher, ou demande de geste : l'agent achats négocie TOUT DE SUITE ce volume avec nos producteurs
    (tous en même temps, visible sur l'écran), puis l'ERP dit la remise possible (une part du gain est rendue au client, 5 % max).
    N'écrit rien dans la commande. Dis `say` tel quel, puis demande son accord ; après son oui : apply_volume_discount avec `pct` et
    `sourcingId`. Negotiate this volume with the producers now, then the discount the ERP allows.
    """
    from app.agent.speak_fr import say_number, say_price  # here: app.agent imports the tools
    from app.market.express import source

    sourcing_id, negotiated_cost = None, None
    try:  # the buying agent: every producer at once, on the screens; never blocks the answer
        src = await source(ctx.erp, product_id, qty, client_id, delivery_date, replay=True, volume=True)
        sourcing_id = src.get("sourcingId")
        if src.get("blendedCost") and src["blendedCost"] < (src.get("usualCost") or float("inf")):
            negotiated_cost = src["blendedCost"]
    except Exception as e:  # noqa: BLE001
        print(f"[discount] producers' negotiation skipped ({type(e).__name__}: {e})", flush=True)
    o = await _offer(ctx, client_id, product_id, qty, requested_pct, negotiated_cost)
    per = PER.get(unit or "", None)
    tail = f" {'la' if per in ('pièce', 'douzaine') else 'le'} {per}" if per else ""
    if o.get("eligible"):
        lead = "J'ai pu négocier avec nos producteurs : " if o.get("negotiated") else "Pour ce volume, "
        say = (f"{lead}je peux vous faire {say_number(o['pct'])} pour cent : "
               f"{say_price(o['unitPrice'])}{tail} au lieu de {say_price(o['listUnitPrice'])}{tail}, {o['condition']}.")  # fmt: skip
    else:
        say = o.get("say") or "C'est déjà son tarif."
    if requested_pct and o.get("eligible") and requested_pct > o["pct"] and not o.get("needsManager"):
        say += f" {say_number(requested_pct)} pour cent, je ne peux pas sur ce volume."
    if o.get("needsManager"):
        say += f" Au-delà de {say_number(o['maxPct'])} pour cent, c'est {o['manager']} qui décide : je lui transmets votre demande ?"
    return {**{k: o.get(k) for k in ("eligible", "pct", "unitPrice", "listUnitPrice", "saved", "needsManager", "reason", "negotiated")},
            "say": say, **({"sourcingId": sourcing_id} if sourcing_id and o.get("negotiated") else {}),
            "next": "Après son oui : apply_volume_discount(orderId, productId, pct, sourcingId)." if o.get("eligible") else None}  # fmt: skip


@tool
async def apply_volume_discount(
    ctx: ToolContext,
    order_id: str = Field(description="La commande (brouillon) qui contient la ligne"),
    product_id: str = Field(description="Le produit de la ligne"),
    pct: float = Field(description="Le pourcentage proposé par propose_volume_discount et accepté par l'appelant"),
    sourcing_id: str | None = Field(None, description="sourcingId renvoyé par propose_volume_discount, s'il y en a un"),
) -> dict:
    """
    Applique la remise acceptée sur la ligne et, si elle vient d'une négociation producteurs, passe leurs bons de commande.
    L'ERP la recalcule : jamais plus que permis. Ensuite, récapitule avec le nouveau total. Apply the accepted discount.
    """
    from app.market.express import SOURCINGS, place_orders

    order = await ctx.erp.get(f"/api/orders/{enc(order_id)}")
    if order.get("status") != "draft":
        raise ValueError("Remise possible seulement sur un brouillon (la commande est déjà confirmée).")
    line = next((x for x in order.get("lines") or [] if x["productId"] == product_id), None)
    if line is None:
        raise ValueError("Ce produit n'est pas dans la commande.")
    s = SOURCINGS.get(sourcing_id or "")
    cost = None
    if s is not None and getattr(s, "volume", False) and s.line.product_id == product_id:
        d = s.script.decision
        covered = sum(a.qty for a in d.allocations)
        qty = float(line["qty"])
        cost = (sum(a.qty * a.price for a in d.allocations) + max(0.0, qty - covered) * s.line.cost) / qty if qty else None
    o = await _offer(ctx, order["clientId"], product_id, float(line["qty"]), pct, cost)
    if not o.get("eligible") or pct > o["pct"] + 1e-9:
        raise ValueError(f"Remise refusée : au plus {o.get('pct', 0)} % sur cette ligne.")
    out = await written(ctx, await ctx.erp.patch(f"/api/orders/{enc(order_id)}/lines/{enc(line['id'])}", {"unitPrice": o["unitPrice"]}))
    if s is not None and cost is not None and not s.orders:  # the producers' volume behind the better price
        out["supplierOrders"] = (await place_orders(ctx.erp, s.id))["orders"]
    return out


# ── « Le comité de prix »: four agents at once, the ERP's arbiter, two offers to the caller ──


def _say_option(o: dict, per: str | None, asked: float) -> str:
    from app.agent.speak_fr import say_number, say_price, say_qty

    tail = f" {'la' if per in ('pièce', 'douzaine') else 'le'} {per}" if per else ""
    head = "pour " + say_qty(o["qty"], o["unit"]) if o["qty"] > asked + 1e-9 else "pour cette quantité"
    if o["pct"] <= 0:
        return f"{head}, c'est {say_price(o['unitPrice'])}{tail}, votre tarif"
    return f"{head}, je peux vous faire {say_price(o['unitPrice'])}{tail}, soit {say_number(o['pct'])} pour cent de moins"


@tool
async def propose_deal(
    ctx: ToolContext,
    client_id: str = Field(description="Le client (cli_…)"),
    product_id: str = Field(description="Le produit (prd_…)"),
    qty: float = Field(description="Quantité demandée, dans l'unité du produit"),
    delivery_date: str | None = Field(None, description="Jour de livraison voulu (AAAA-MM-JJ), si dit"),
    objection: bool = Field(True, description="L'appelant trouve le prix trop cher ou demande un geste"),
) -> dict:
    """
    Grosse commande ou « c'est trop cher » : le comité de prix (achat auprès des producteurs, stock et dates courtes, crédit, habitudes
    du client) travaille EN MÊME TEMPS, puis l'ERP choisit les deux meilleures offres. N'écrit rien. Dis `say` tel quel (deux options,
    il choisit), puis après son choix : apply_deal(orderId, dealId, option). Price committee: two offers decided by the ERP.
    """
    from app.services.deal_desk import run

    deal = await run(ctx.erp, client_id, product_id, qty, delivery_date, objection)
    opts, panel = deal["options"], deal["panel"]
    if deal.get("blocked"):
        return {"dealId": panel["dealId"], "options": [], "say": "Je ne peux pas faire de geste sur ce compte pour l'instant."}
    keys = [k for k in (panel["chosen"], panel["alternative"]) if k]
    shown = sorted((opts[k] for k in keys), key=lambda o: o["qty"])
    unit = shown[0]["unit"] if shown else None
    per = PER.get(unit or "", None)
    if len(shown) == 1:
        say = _say_option(shown[0], per, qty)[0].upper() + _say_option(shown[0], per, qty)[1:] + "."
    else:
        a, b = (_say_option(o, per, qty) for o in shown)
        say = f"{a[0].upper()}{a[1:]}. Et {b}. Lequel vous préférez ?"
    safe = [{k: o[k] for k in ("key", "qty", "unit", "pct", "unitPrice", "total")} for o in shown]
    return {"dealId": panel["dealId"], "options": safe, "say": say,
            "next": "Il choisit, puis : apply_deal(orderId, dealId, option = key choisie). Plus de 5 % demandés : Jean-Marc décide."}  # fmt: skip


@tool
async def apply_deal(
    ctx: ToolContext,
    order_id: str = Field(description="La commande (brouillon) qui contient le produit"),
    deal_id: str = Field(description="dealId renvoyé par propose_deal"),
    option: str = Field(description="La clé de l'option choisie par l'appelant (A, B ou C)"),
) -> dict:
    """
    Écrit l'option choisie sur la ligne (quantité et prix), après l'avoir fait recalculer par l'ERP, et passe les bons des producteurs si
    le prix vient de leur négociation. Ensuite, récapitule avec le nouveau total et « Je valide ? ». Apply the chosen deal option.
    """
    from app.market.express import place_orders
    from app.services.deal_desk import DEALS

    deal = DEALS.get(deal_id)
    if not deal:
        raise ValueError("Offre expirée : refais propose_deal.")
    order = await ctx.erp.get(f"/api/orders/{enc(order_id)}")
    if order.get("status") != "draft" or order.get("clientId") != deal["clientId"]:
        raise ValueError("Offre applicable seulement au brouillon de ce client.")
    line = next((x for x in order.get("lines") or [] if x["productId"] == deal["productId"]), None)
    if line is None:
        raise ValueError("Ce produit n'est pas dans la commande.")
    q = {"clientId": deal["clientId"], "productId": deal["productId"], "qty": deal["qty"],
         **({"negotiatedCost": round(deal["negotiatedCost"], 4)} if deal.get("negotiatedCost") else {})}  # fmt: skip
    fresh = {o["key"]: o for o in (await ctx.erp.get("/api/prices/deal-options", q))["options"]}
    o = fresh.get(option.strip().upper())
    if o is None:
        raise ValueError(f"Option {option} indisponible maintenant : options {sorted(fresh)}.")
    out = await written(ctx, await ctx.erp.patch(f"/api/orders/{enc(order_id)}/lines/{enc(line['id'])}",
                                                 {"qty": o["qty"], "unitPrice": o["unitPrice"]}))  # fmt: skip
    if deal.get("sourcingId") and o["pct"] > 0:
        out["supplierOrders"] = (await place_orders(ctx.erp, deal["sourcingId"]))["orders"]
    return out
