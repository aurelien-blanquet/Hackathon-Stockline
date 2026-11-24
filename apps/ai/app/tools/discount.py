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
