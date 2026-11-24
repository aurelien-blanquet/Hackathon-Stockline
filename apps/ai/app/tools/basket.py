"""build_basket: « fais-moi le panier optimal pour 400 € » — the ERP builds it (backend services/basket.py): the whole
budget used, balanced, leaning discreetly toward what earns the most. The model says the list; the screen shows it."""

from pydantic import BaseModel, Field

from .registry import ToolContext, tool


class BasketItem(BaseModel):
    product_id: str = Field(alias="productId", description="Le produit (prd_…), résolu par find_product")
    share: float | None = Field(None, description="Poids dans le budget (défaut 1). « trop de X » → X à 0.6 ; « plus de X » → X à 1.6 ; les autres à 1")

    model_config = {"populate_by_name": True}


@tool
async def build_basket(
    ctx: ToolContext,
    client_id: str = Field(description="Le client (cli_…)"),
    budget: float = Field(description="Le budget du client en € HT"),
    items: list[BasketItem] = Field(description="Les produits du panier (et leur poids si le client a demandé un équilibre)"),
) -> dict:
    """
    Panier optimal pour un budget : l'ERP répartit TOUT le budget entre les produits, équilibré, en unités réelles. Pour rééquilibrer
    (« trop de reblochon »), rappelle-le avec d'autres `share` : le budget reste le même. Dis `say` (une courte liste), l'écran montre
    le détail. N'écrit rien : après son oui, create_draft_order avec `lines`. Build a basket to the client's budget.
    """
    from app.agent.speak_fr import say_price

    from .voice import say_line

    body = {"clientId": client_id, "budget": budget, "items": [{"productId": i.product_id, "share": i.share or 1.0} for i in items]}
    b = await ctx.erp.post("/api/prices/basket", body)
    lines = [{k: x[k] for k in ("productId", "name", "unit", "qty", "unitPrice", "lineTotal")} for x in b["lines"]]  # no margin
    spoken = [say_line(x["qty"], x["unit"], x["name"]) for x in lines]
    say = f"Pour {say_price(budget)}, je vous propose " + ", ".join(spoken[:-1]) + (" et " if len(spoken) > 1 else "") + spoken[-1]
    say += f", soit {say_price(b['total'])}. Ça vous va ?"
    return {"lines": lines, "total": b["total"], "budget": budget, "budgetUsedPct": b["budgetUsedPct"], "say": say,
            "next": "Après son oui : create_draft_order(lines = productId + qty). Rééquilibrage : build_basket avec d'autres share, même budget."}  # fmt: skip
