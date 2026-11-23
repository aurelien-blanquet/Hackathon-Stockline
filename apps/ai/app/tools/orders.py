"""Write tools: build an order step by step (draft → lines → confirm), and change it when the caller changes their
mind (update / remove a line, move the delivery date, cancel). Business rules live in the ERP API.

Every result carries `say`: the order read back in spoken French, built in code (never by the model), so the recap
the caller hears matches the ERP exactly."""

from pydantic import Field

from .erp import enc, pick
from .history import without_none
from .registry import ToolArgs, ToolContext, tool


class OrderLine(ToolArgs):
    product_id: str
    qty: float = Field(description="Quantité dans l'unité du produit (kg, pièce, caisse…)")
    note: str | None = Field(None, description="ex. « livrer avant 7 h », « bien mûr »")
    substitute_for: str | None = Field(None, description="productId remplacé, si c'est une substitution")

    def to_erp(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)


async def order_result(o: dict) -> dict:
    """summarize_order + the spoken recap (needs the ERP's business date for « demain »)."""
    from .voice import _today

    return {**summarize_order(o), "say": say_order(o, await _today())}


def say_order(o: dict, today: str | None) -> str:
    """« quatre Reblochon de Savoie AOP laitier et deux kilos de Tomme de Savoie IGP, livraison demain, total
    quarante-sept euros hors taxes »."""
    from app.agent.speak_fr import say_date, say_price

    from .voice import say_line

    lines = [say_line(line["qty"], line.get("unit") or "", line.get("productName") or "") for line in o.get("lines") or []]
    what = "aucune ligne" if not lines else lines[0] if len(lines) == 1 else f"{', '.join(lines[:-1])} et {lines[-1]}"
    parts = [what]
    if o.get("deliveryDate"):
        parts.append(f"livraison {say_date(o['deliveryDate'], today)}")
    if o.get("totalHt") is not None and lines:
        parts.append(f"total {say_price(o['totalHt'])} hors taxes")
    return ", ".join(parts)


def summarize_order(o: dict) -> dict:
    """What the model gets back after any order operation: short, with line ids for later edits."""
    return {
        **pick(o, "id", "number", "status"),
        "client": (o.get("client") or {}).get("name"),
        **pick(o, "deliveryDate", "totalHt"),
        "lines": [
            {
                "lineId": line["id"],
                **pick(line, "productId", "productName", "qty", "unit", "unitPrice", "available"),
                **({"note": line["note"]} if line.get("note") else {}),
            }
            for line in o["lines"]
        ],
        "warnings": o.get("warnings") or [],
    }


@tool
async def create_draft_order(
    ctx: ToolContext,
    client_id: str,
    delivery_date: str | None = Field(None, description="YYYY-MM-DD, optionnel"),
    lines: list[OrderLine] | None = None,
    note: str | None = None,
) -> dict:
    """
    Crée une pré-commande (brouillon) pour un client, avec ou sans lignes. Prix résolus par l'ERP (prix client > catalogue).
    Create a draft order. Delivery date defaults to the client's next delivery day.
    """
    body = {
        "clientId": client_id,
        "deliveryDate": delivery_date,
        "lines": [line.to_erp() for line in lines] if lines is not None else None,
        "note": note,
        "source": "voice_agent" if ctx.actor == "voice_agent" else "web",
    }
    return await order_result(await ctx.erp.post("/api/orders", without_none(body)))


@tool
async def add_order_line(
    ctx: ToolContext,
    order_id: str,
    product_id: str,
    qty: float = Field(description="Quantité dans l'unité du produit (kg, pièce, caisse…)"),
    note: str | None = Field(None, description="ex. « livrer avant 7 h », « bien mûr »"),
    substitute_for: str | None = Field(None, description="productId remplacé, si c'est une substitution"),
) -> dict:
    """
    Ajoute une ligne (un NOUVEAU produit) à une commande brouillon ou confirmée. Si le produit est déjà sur la commande,
    utilise update_order_line pour changer sa quantité (pas de doublon). Add a line to an order.
    """
    line = OrderLine(product_id=product_id, qty=qty, note=note, substitute_for=substitute_for)
    return await order_result(await ctx.erp.post(f"/api/orders/{enc(order_id)}/lines", line.to_erp()))


@tool
async def update_order_line(
    ctx: ToolContext,
    order_id: str,
    line_id: str = Field(description="lineId renvoyé dans `lines` de la commande"),
    qty: float | None = Field(None, description="Nouvelle quantité (remplace l'ancienne, ne s'ajoute pas)"),
    product_id: str | None = Field(None, description="Autre produit à la place (ex. « finalement du laitier, pas du fermier »)"),
    note: str | None = None,
) -> dict:
    """
    Modifie une ligne quand l'appelant change d'avis : « plutôt quinze », « non, mets du fermier à la place ». La nouvelle quantité
    REMPLACE l'ancienne. Brouillon ou commande confirmée. Change a line's quantity or product (change of mind).
    """
    patch = without_none({"qty": qty, "productId": product_id, "note": note})
    if not patch:
        raise ValueError("Rien à modifier : donne qty, product_id ou note")
    return await order_result(await ctx.erp.patch(f"/api/orders/{enc(order_id)}/lines/{enc(line_id)}", patch))


@tool
async def remove_order_line(ctx: ToolContext, order_id: str, line_id: str = Field(description="lineId de la ligne à retirer")) -> dict:
    """Retire un produit de la commande (« enlève le beurre »). Remove a line from a draft or confirmed order."""
    return await order_result(await ctx.erp.delete(f"/api/orders/{enc(order_id)}/lines/{enc(line_id)}"))


@tool
async def update_order(
    ctx: ToolContext,
    order_id: str,
    delivery_date: str | None = Field(None, description="Nouvelle date de livraison YYYY-MM-DD (un jour de livraison du client)"),
    note: str | None = Field(None, description="Consigne de livraison, ex. « avant 9 h, porte de service »"),
) -> dict:
    """Change la date de livraison ou la consigne d'une commande (brouillon ou confirmée). Change delivery date / note."""
    patch = without_none({"deliveryDate": delivery_date, "note": note})
    if not patch:
        raise ValueError("Rien à modifier : donne delivery_date ou note")
    return await order_result(await ctx.erp.patch(f"/api/orders/{enc(order_id)}", patch))


@tool
async def cancel_order(ctx: ToolContext, order_id: str) -> dict:
    """
    Annule une commande (libère le stock réservé). Seulement si l'appelant demande clairement d'annuler TOUTE la commande ;
    pour un seul produit, utilise remove_order_line. Cancel a whole order.
    """
    return await order_result(await ctx.erp.post(f"/api/orders/{enc(order_id)}/cancel"))


@tool
async def confirm_order(ctx: ToolContext, order_id: str) -> dict:
    """
    Confirme une commande : réserve le stock et l'affecte à une tournée. Renvoie des alertes (encours, stock…).
    Only after the caller explicitly agreed to the recap.
    """
    return await order_result(await ctx.erp.post(f"/api/orders/{enc(order_id)}/confirm"))


@tool
async def get_order(ctx: ToolContext, order_id: str) -> dict:
    """Détail d'une commande (lignes, statut, total, alertes). Order detail."""
    return await order_result(await ctx.erp.get(f"/api/orders/{enc(order_id)}"))
