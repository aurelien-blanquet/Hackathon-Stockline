"""Market tools for the phone: the central buying agent, run during a customer call (app/market/express.py)."""

from pydantic import Field

from .registry import ToolContext, tool


@tool
async def source_product(
    ctx: ToolContext,
    product_id: str = Field(description="ex. prd_0012 (from find_product / identify_caller)"),
    qty: float = Field(description="Quantité TOTALE voulue par le client, dans l'unité du produit"),
    client_id: str | None = Field(None, description="ex. cli_0027"),
    delivery_date: str | None = Field(None, description="YYYY-MM-DD : date de livraison du client (défaut : demain)"),
) -> dict:
    """
    Marché express : quand le stock ne suffit pas pour un produit que le client veut (rupture ou quantité trop
    grande, et pas de remplacement accepté), l'agent achats appelle en même temps tous les producteurs qui peuvent le
    fournir, les met en concurrence et renvoie la meilleure solution pour la quantité manquante : qui, combien, à quel
    prix, arrivée quand (`say` = la phrase à dire). Instantané. Ne commande rien chez les producteurs : après le oui du
    client, appelle create_supplier_orders. Sources the missing quantity from all suppliers at once.
    """
    from app.market.express import source

    return await source(ctx.erp, product_id, qty, client_id, delivery_date)


@tool
async def create_supplier_orders(
    ctx: ToolContext,
    sourcing_id: str = Field(description="sourcingId renvoyé par source_product"),
) -> dict:
    """
    Passe chez les producteurs retenus les bons de commande du marché express `sourcingId` (brouillons, prix
    négociés). Seulement après le oui du client à la solution proposée. Rejouable sans doublon.
    Places the supplier purchase orders of an express sourcing.
    """
    from app.market.express import place_orders

    return await place_orders(ctx.erp, sourcing_id)
