"""sales_coach: how to answer THIS caller now (services/sales_posture.py). Filled in by the system before the model
answers when the caller hesitates, objects on price, compares, is about to leave or is convinced."""

from pydantic import Field

from .registry import ToolContext, tool


@tool
async def sales_coach(
    ctx: ToolContext,
    signals: list[str] = Field(default_factory=list, description="Ce que montre l'appelant : price, competitor, hesitant, leaving, quality, convinced, refusal"),
) -> dict:
    """
    Posture de vente pour ce tour (déjà fournie par le système quand c'est utile : ne l'appelle pas toi-même). Suis `do`, utilise
    seulement `use`, en une ou deux phrases naturelles, jamais de pression. Sales stance for this turn.
    """
    return {"stance": "normal", "do": "Réponds normalement.", "signals": signals}
