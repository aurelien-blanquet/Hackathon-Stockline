"""
The seller adapts to the customer (consultative selling): read how the caller acts, choose a stance, give the model the
arguments to use, all decided in code before the model answers. The model then says it in its own words.

    signals    what the caller's sentence shows: hesitant, price objection, competitor, about to leave, quality doubt,
               convinced, refusal (regexes on French phone talk; several can hold at once)
    stance     one per turn, the strongest signal wins:
                 refusal (2nd)  → respect it, drop the topic
                 convinced      → close: short recap, no extra pitch
                 leaving        → keep the door open, no pressure (« je vous le garde jusqu'à demain midi ? »)
                 price / rival  → the concession ladder, ONE step per objection:
                                  1 value (facts) → 2 reframe (price per portion) → 3 honest cheaper alternative
                                  → 4 trade-off offer (propose_deal: ≤ 5 %, profit kept) → 5 Jean-Marc decides
                 quality doubt  → reassure with facts
                 hesitant       → one question about the need, then advise (sometimes the cheaper choice)
    arguments  only from data: product name / origin / caliber / AOP / sales of the month / stock, a cheaper product
               of the same family, the price per portion. Never invented, never a fake « last chance ».

Limits: at most one push per topic and one discount per call; advice may go against the sale (it builds trust).
"""

import re
from dataclasses import dataclass, field

from app.schemas import ChatMessage

S = re.IGNORECASE
SIGNALS = {
    "refusal": re.compile(r"\b(?:non merci|ça ira|ca ira|pas la peine|pas besoin|j'en veux pas|laisse(?:z)? tomber|on oublie)\b", S),
    "leaving": re.compile(r"\b(?:je vais réfléchir|je vais reflechir|je (?:vous|te) rappelle|je reviens vers|on verra|je vais voir)\b", S),
    "competitor": re.compile(r"\b(?:ailleurs|concurren\w*|chez (?:metro|promocash|transgourmet|un autre|l'autre)|moins cher chez|on me (?:le )?(?:fait|propose))\b", S),
    "price": re.compile(r"\b(?:(?:trop |un peu |vachement |assez )?cher|ça fait beaucoup|ca fait beaucoup|c'est beaucoup|un (?:petit )?(?:effort|geste)|une remise|un prix|"
                        r"(?:moins|mieux) que ça|négocier|negocier|budget|ça pique)\b", S),
    "quality": re.compile(r"\b(?:il est bon|elle est bonne|c'est bon (?:en ce moment|ce mois)|la qualité|ça se vend|ca se vend|frais|affin\w+|ça vaut le coup|ca vaut le coup)\b.*\?", S),
    "hesitant": re.compile(r"(?:^|\b)(?:bof|bon\.\.\.|euh|hmm|je sais pas|je ne sais pas|faut voir|pas sûr|pas sur|peut-être|peut etre|j'hésite|j'hesite)\b", S),
    "convinced": re.compile(r"\b(?:parfait|top|super|vas-y|allez-y|banco|ça marche|ca marche|d'accord|ok|go|je prends|on fait comme ça|va pour)\b", S),
}
PORTION_KG = {"raclette": 0.2, "fondue": 0.2, "tomme": 0.1, "beaufort": 0.1, "abondance": 0.1, "reblochon": 0.15, "persillé": 0.1}
LADDER = ["value", "reframe", "alternative", "deal", "manager"]


@dataclass
class Posture:
    """Per call: how far down the concession ladder, what was already tried, refusals heard."""

    step: int = 0  # next ladder step (0 = value)
    discount_offered: bool = False
    refusals: int = 0
    last: str | None = None  # last stance, for the screen
    tried: list[str] = field(default_factory=list)


def signals(text: str) -> list[str]:
    found = [name for name, rx in SIGNALS.items() if rx.search(text or "")]
    if "convinced" in found and any(s in found for s in ("price", "competitor", "leaving", "refusal", "hesitant")):
        found.remove("convinced")  # « d'accord mais c'est cher » is an objection, not a yes
    return found


def product_in_talk(history: list[ChatMessage]) -> str | None:
    """The product being discussed: the last one a tool resolved or an order line carries."""
    import json

    for m in reversed(history):
        if m.role != "tool":
            continue
        try:
            r = json.loads(m.content)
        except (ValueError, TypeError):
            continue
        if not isinstance(r, dict):
            continue
        if isinstance(r.get("product"), dict) and r["product"].get("id"):
            return r["product"]["id"]
        for line in reversed(r.get("lines") or []):
            if isinstance(line, dict) and line.get("productId"):
                return line["productId"]
        for p in r.get("products") or []:
            if isinstance(p, dict) and isinstance(p.get("product"), dict):
                return p["product"].get("id")
    return None


async def arguments(erp, product_id: str, client_price: float | None = None) -> dict:
    """Facts a good seller would use, from the ERP only (nothing invented)."""
    p = await erp.get(f"/api/products/{product_id}")
    name, unit = p.get("name") or "", p.get("unit") or "kg"
    low = name.lower()
    facts: list[str] = []
    if "aop" in low:
        facts.append("AOP : appellation contrôlée, le vrai produit de Savoie")
    if "igp" in low:
        facts.append("IGP Savoie")
    if "fermier" in low:
        facts.append("fermier : fait à la ferme, au lait cru d'un seul troupeau")
    if "lait cru" in low:
        facts.append("au lait cru")
    if p.get("origin"):
        facts.append(f"origine : {p['origin']}")
    if (sold := p.get("sales30d")) and isinstance(sold, int | float) and sold > 0:
        facts.append(f"un de nos produits qui tournent : {sold:g} {unit} vendus ce mois-ci")
    price = client_price or p.get("price")
    portion = next((kg for key, kg in PORTION_KG.items() if key in low), None)
    per_portion = None
    if price and unit == "kg" and portion:
        per_portion = {"grams": int(portion * 1000), "price": round(price * portion, 2)}
    elif price and unit == "piece" and "450 g" in low:
        per_portion = {"grams": 150, "price": round(price / 3, 2)}  # a 450 g reblochon = 3 portions of 150 g
    cheaper = None
    try:
        alts = await erp.get(f"/api/products/{product_id}/alternatives")
        same_unit = [a for a in alts or [] if a.get("unit") == unit and a.get("price") and price and a["price"] < price and (a.get("available") or 0) > 0]
        if same_unit:
            a = max(same_unit, key=lambda a: a["price"])  # the closest cheaper one, not the cheapest
            cheaper = {"name": a["name"].split(" (")[0], "price": a["price"]}
    except Exception:  # noqa: BLE001 — no alternative: the ladder skips that step
        pass
    return {"product": name.split(" (")[0], "unit": unit, "facts": facts[:3], "perPortion": per_portion, "cheaper": cheaper}


def coach(state: Posture, sig: list[str], args: dict | None) -> dict | None:
    """The stance for this turn (None: nothing special, the model answers normally)."""
    if not sig:
        return None
    a = args or {}
    if "refusal" in sig:
        state.refusals += 1
        if state.refusals >= 2 or state.discount_offered:
            state.last = "respecte le non"
            return {"stance": "respect", "do": "Il a dit non : n'insiste plus. « Pas de souci. » puis passe à la suite (ou au récap)."}
    if "convinced" in sig and not any(s in sig for s in ("price", "competitor")):
        state.last = "conclut"
        return {"stance": "close", "do": "Il est convaincu : conclus vite, récap court + « Je valide ? ». Aucun argument de plus."}
    if "leaving" in sig and "price" not in sig:
        state.last = "laisse la porte ouverte"
        return {"stance": "keep_door_open", "do": "Sans pression : propose de lui garder (« Je vous le garde jusqu'à demain midi ? »). Pas de remise pour le retenir."}
    if "price" in sig or "competitor" in sig:
        while state.step < len(LADDER):
            move = LADDER[state.step]
            state.step += 1
            if move == "value" and not a.get("facts"):
                continue
            if move == "reframe" and not a.get("perPortion"):
                continue
            if move == "alternative" and not a.get("cheaper"):
                continue
            if move == "deal" and state.discount_offered:
                continue
            break
        else:
            move = "manager"
        state.tried.append(move)
        state.last = f"objection prix → {move} ({min(state.step, len(LADDER))}/{len(LADDER)})"
        rival = " Ne dénigre jamais le concurrent." if "competitor" in sig else ""
        if move == "value":
            return {"stance": "justify_value", "use": a["facts"], "do": "Valide son ressenti en trois mots (« Je comprends. »), montre la valeur avec UN de ces faits, ce que ÇA LUI APPORTE (ses clients, ses ventes), puis une relance douce vers le oui (« On part là-dessus ? », « Je vous les mets ? »). Ne propose PAS d'autre produit ni de remise à ce stade, ne lui demande pas s'il veut autre chose." + rival}
        if move == "reframe":
            pp = a["perPortion"]
            return {"stance": "reframe", "use": [f"{pp['price']} € la portion de {pp['grams']} grammes"],
                    "do": "Ramène le prix à la portion (« ça fait … la part »), dis ce que ça lui rapporte, puis relance douce vers le oui. Pas encore d'autre produit." + rival}  # fmt: skip
        if move == "alternative":
            c = a["cheaper"]
            return {"stance": "honest_alternative", "use": [f"{c['name']} à {c['price']} €"],
                    "do": "Conseil honnête : propose ce produit moins cher s'il convient à son usage ; c'est lui qui choisit." + rival}  # fmt: skip
        if move == "deal":
            state.discount_offered = True
            return {"stance": "trade_off_offer", "do": "Appelle propose_deal (le brouillon doit exister) et dis son `say` : une offre en échange de quelque chose (volume, lot)." + rival}
        return {"stance": "manager", "do": "Tu es allée au bout de ce que tu peux faire : au-delà, c'est Jean-Marc qui décide ; propose de lui transmettre, sans insister."}
    if "quality" in sig:
        state.last = "rassure (qualité)"
        return {"stance": "reassure", "use": a.get("facts") or [], "do": "Rassure avec un fait concret (origine, appellation, ce qui se vend), une phrase. Pas de superlatif vide."}
    if "hesitant" in sig:
        state.last = "comprend le besoin"
        return {"stance": "discover_need", "do": "Il hésite : UNE question sur son besoin (pour quoi, combien de couverts, quel jour), puis conseille — même le moins cher si c'est mieux pour lui."}
    return None
