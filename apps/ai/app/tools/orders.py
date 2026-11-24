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

    today = await _today()
    long = len(o.get("lines") or []) > SAY_LINES_MAX
    return {**summarize_order(o), "say": say_order(o, today), **({"sayAll": say_order(o, today, compact=False)} if long else {})}


SAY_LINES_MAX = 3  # beyond this, a spoken recap is the product count + total (s01: 8 lines read aloud = 806 chars)


def say_order(o: dict, today: str | None, compact: bool = True) -> str:
    """« quatre Reblochon de Savoie AOP laitier et deux kilos de Tomme de Savoie IGP, livraison demain, total
    quarante-sept euros hors taxes ». More than SAY_LINES_MAX lines: « huit produits, livraison demain, total … »."""
    from app.agent.speak_fr import say_date, say_int, say_price

    from .voice import say_line

    lines = [say_line(line["qty"], line.get("unit") or "", line.get("productName") or "") for line in o.get("lines") or []]
    if compact and len(lines) > SAY_LINES_MAX:
        what = f"{say_int(len(lines))} produits"
    else:
        what = "aucune ligne" if not lines else lines[0] if len(lines) == 1 else f"{', '.join(lines[:-1])} et {lines[-1]}"
    parts = [what]
    if o.get("deliveryDate"):
        parts.append(f"livraison {say_date(o['deliveryDate'], today)}")
    if o.get("totalHt") is not None and lines:
        parts.append(f"total {say_price(o['totalHt'])} hors taxes")
    return ", ".join(parts)


async def written(ctx: ToolContext, o: dict) -> dict:
    """order_result + the producers' orders of an express sourcing this order needs (placed in code, see
    market/express.py place_for_order): the model does not have to remember create_supplier_orders."""
    from app.market.express import place_for_order

    out = await order_result(o)
    if placed := await place_for_order(ctx.erp, o):
        out["supplierOrders"] = placed
        out["note"] = "Bons de commande producteurs passés automatiquement : n'appelle pas create_supplier_orders."
    return out


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
    return await written(ctx, await ctx.erp.post("/api/orders", without_none(body)))


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
    return await written(ctx, await ctx.erp.post(f"/api/orders/{enc(order_id)}/lines", line.to_erp()))


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
    return await written(ctx, await ctx.erp.patch(f"/api/orders/{enc(order_id)}/lines/{enc(line_id)}", patch))


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
    o = await ctx.erp.post(f"/api/orders/{enc(order_id)}/confirm")
    out = await order_result(o)
    if o.get("status") == "confirmed":  # the customer gets the written recap at once (recorded on the client file)
        if sent := await send_recap(ctx, o):
            out["customerMessage"] = sent
    return out


# ── the written recap sent to the customer the moment the order is confirmed ──

UNIT_SHORT = {"kg": "kg", "piece": "", "liter": "L", "box": "cartons", "dozen": "douz."}
RECAP_LINES = 4
_background: set = set()


def recap_text(o: dict, today: str | None) -> str:
    """« Crèmerie des Aravis — commande 124 confirmée. 20 kg Tomme de Savoie IGP · 6 kg Raclette tranchée. Livraison
    samedi 28/11. Total 310,00 € HT. Facture à la livraison. Merci Antoine ! » — short enough for one SMS screen."""
    from datetime import date

    from .voice import short_name

    lines = o.get("lines") or []
    def one(line: dict) -> str:
        q = line.get("qty") or 0
        q_txt = f"{q:g}".replace(".", ",")
        unit = UNIT_SHORT.get(line.get("unit") or "", line.get("unit") or "")
        return f"{q_txt} {unit} {short_name(line.get('productName') or '')}".replace("  ", " ").strip()
    shown = " · ".join(one(line) for line in lines[:RECAP_LINES])
    if len(lines) > RECAP_LINES:
        shown += f" + {len(lines) - RECAP_LINES} autres produits"
    when = ""
    if o.get("deliveryDate"):
        d = date.fromisoformat(o["deliveryDate"][:10])
        days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        when = f" Livraison {days[d.weekday()]} {d.strftime('%d/%m')}."
    amount = f"{o['totalHt']:,.2f}".replace(",", " ").replace(".", ",") if o.get("totalHt") is not None else None
    total = f" Total {amount} € HT." if amount else ""
    number = (o.get("number") or "").split("-")[-1].lstrip("0") or o.get("number") or ""
    first = (recap_contact(o.get("client") or {}).get("name") or "").split()[:1]
    first = first[0] if first else ""
    thanks = f" Merci {first} !" if first else " Merci !"
    return f"Crèmerie des Aravis — commande {number} confirmée : {shown}.{when}{total} Facture à la livraison.{thanks}"


def recap_contact(client: dict) -> dict:
    contacts = client.get("contacts") or [{}]
    return next((c for c in contacts if "command" in (c.get("role") or "").lower()), contacts[0]) or {}


def recap_channel(client: dict) -> tuple[str, str] | None:
    """(channel, recipient): WhatsApp if the client orders that way, else SMS to the first contact's mobile, else email."""
    contact = recap_contact(client)  # the person who places the orders (« gère les commandes »), not always the boss
    habits = " ".join([client.get("preferences") or "", *[n.get("text", "") for n in client.get("notes") or [] if isinstance(n, dict)]]).lower()
    who = contact.get("name") or client.get("name") or ""
    if contact.get("phone") and "whatsapp" in habits:
        return "whatsapp", f"{who} · {contact['phone']}"
    if contact.get("phone"):
        return "sms", f"{who} · {contact['phone']}"
    if contact.get("email"):
        return "email", f"{who} · {contact['email']}"
    return None  # no number, no address: nothing to send to


async def send_recap(ctx: ToolContext, o: dict) -> dict | None:
    """The recap is composed now (no model, no wait) and written on the client file in the background (client event,
    channel sms / whatsapp / email): the confirmation reply is never delayed by it. No real SMS gateway in the kit:
    the message is what would be sent, recorded where the team sees it."""
    import asyncio

    from .voice import _today

    client = o.get("client") or {}
    if not (where := recap_channel(client)):
        return None
    channel, to = where
    text = recap_text(o, await _today())
    if client.get("id"):
        body = {"type": "note", "channel": channel, "title": f"Récapitulatif de commande envoyé ({channel.upper() if channel == 'sms' else channel})",
                "description": f"À {to} : {text}", "orderId": o.get("id"), "author": "Agent vocal"}  # fmt: skip
        task = asyncio.create_task(ctx.erp.post(f"/api/clients/{enc(client['id'])}/events", body))
        _background.add(task)
        task.add_done_callback(_background.discard)
    return {"channel": channel, "to": to, "text": text}


@tool
async def get_order(ctx: ToolContext, order_id: str) -> dict:
    """Détail d'une commande (lignes, statut, total, alertes). Order detail."""
    return await order_result(await ctx.erp.get(f"/api/orders/{enc(order_id)}"))
