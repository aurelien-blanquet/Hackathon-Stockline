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


async def _offer(ctx: ToolContext, client_id: str, product_id: str, qty: float, requested_pct: float | None) -> dict:
    q = {"clientId": client_id, "productId": product_id, "qty": qty, **({"requestedPct": requested_pct} if requested_pct else {})}
    return await ctx.erp.get("/api/prices/volume-offer", q)


@tool
async def propose_volume_discount(
    ctx: ToolContext,
    client_id: str = Field(description="Le client (cli_…)"),
    product_id: str = Field(description="Le produit (prd_…)"),
    qty: float = Field(description="Quantité de la ligne, dans l'unité du produit"),
    unit: str | None = Field(None, description="Unité du produit (kg, piece…), pour la phrase"),
    requested_pct: float | None = Field(None, description="Remise demandée par l'appelant, en %, s'il en a cité une"),
) -> dict:
    """
    Gros volume ou demande de geste commercial : ce que tu PEUX proposer (lecture seule, n'écrit rien). Dis `say` tel quel, puis demande
    son accord. Après son oui seulement : apply_volume_discount. Jamais d'autre pourcentage que `pct`. Volume discount the ERP allows.
    """
    from app.agent.speak_fr import say_number, say_price  # here: app.agent imports the tools

    o = await _offer(ctx, client_id, product_id, qty, requested_pct)
    per = PER.get(unit or "", None)
    tail = f" {'la' if per in ('pièce', 'douzaine') else 'le'} {per}" if per else ""
    if o.get("eligible"):
        say = (f"Pour ce volume, je peux vous faire {say_number(o['pct'])} pour cent : "
               f"{say_price(o['unitPrice'])}{tail} au lieu de {say_price(o['listUnitPrice'])}{tail}, {o['condition']}.")  # fmt: skip
    else:
        say = o.get("say") or "C'est déjà son tarif."
    if requested_pct and o.get("eligible") and requested_pct > o["pct"] and not o.get("needsManager"):
        say += f" {say_number(requested_pct)} pour cent, je ne peux pas sur ce volume."
    if o.get("needsManager"):
        say += f" Au-delà de {say_number(o['maxPct'])} pour cent, c'est {o['manager']} qui décide : je lui transmets votre demande ?"
    return {**{k: o.get(k) for k in ("eligible", "pct", "unitPrice", "listUnitPrice", "saved", "needsManager", "reason")}, "say": say,
            "next": "Après son oui : apply_volume_discount(orderId, productId, pct)." if o.get("eligible") else None}  # fmt: skip


@tool
async def apply_volume_discount(
    ctx: ToolContext,
    order_id: str = Field(description="La commande (brouillon) qui contient la ligne"),
    product_id: str = Field(description="Le produit de la ligne"),
    pct: float = Field(description="Le pourcentage proposé par propose_volume_discount et accepté par l'appelant"),
) -> dict:
    """
    Applique la remise volume acceptée sur la ligne (prix unitaire de la ligne). L'ERP la recalcule : jamais plus que permis.
    Ensuite, récapitule la commande avec le nouveau total. Apply the accepted volume discount to the order line.
    """
    order = await ctx.erp.get(f"/api/orders/{enc(order_id)}")
    if order.get("status") != "draft":
        raise ValueError("Remise possible seulement sur un brouillon (la commande est déjà confirmée).")
    line = next((x for x in order.get("lines") or [] if x["productId"] == product_id), None)
    if line is None:
        raise ValueError("Ce produit n'est pas dans la commande.")
    o = await _offer(ctx, order["clientId"], product_id, float(line["qty"]), pct)
    if not o.get("eligible") or pct > o["pct"] + 1e-9:
        raise ValueError(f"Remise refusée : au plus {o.get('pct', 0)} % sur cette ligne.")
    return await written(ctx, await ctx.erp.patch(f"/api/orders/{enc(order_id)}/lines/{enc(line['id'])}", {"unitPrice": o["unitPrice"]}))
