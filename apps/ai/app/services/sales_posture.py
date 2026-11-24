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
# Who is calling, and in what state (take priority over selling). French phone talk, lower-case insensitive.
SITUATIONS = {
    "insult": re.compile(r"\b(?:connard|connasse|conne?|idiote?|abruti\w*|débile|crétin\w*|enfoiré\w*|bouffon\w*|ta gueule|ferme-la|"
                         r"nulle? à chier|incompétent\w*|tocard\w*|tu sers à rien|vous servez à rien)\b", S),
    "wrong_number": re.compile(r"\b(?:pizz\w+|médecin|docteur|cabinet médical|taxi|plombier|dentiste|pharmacie|mairie|la banque|"
                               r"je me suis trompée? de numéro|mauvais numéro|faux numéro|c'est pas (?:le|la) bon\w*|je voulais appeler|"
                               r"réserver une table|une table pour)\b", S),
    "prank": re.compile(r"\b(?:canular|c'est une blague|je rigole|mdr|lol|haha|ah ah|un million de|des millions de|mille tonnes|cent tonnes|"
                        r"pour mon (?:chat|chien|hamster)|livr\w+ sur (?:la )?lune|le président de la république)\b", S),
    "robot": re.compile(r"\b(?:(?:vous êtes|t'es|tu es|c'est) (?:un |une )?(?:robot|ia|machine|vraie personne|humaine?)|"
                        r"intelligence artificielle|je parle à (?:un robot|une machine|une ia))\b", S),
    "human": re.compile(r"\b(?:parler à (?:quelqu'un|un humain|une vraie personne|un commercial|un vendeur|jean-marc|votre (?:responsable|patron|chef))|"
                        r"passez-moi|un conseiller|un être humain)\b", S),
    "angry": re.compile(r"\b(?:inadmissible|scandal\w*|en colère|pas content\w*|c'est pas normal|ras[- ]le[- ]bol|marre|la troisième fois|"
                        r"encore en retard|toujours en retard|abîmé\w*|avarié\w*|pourri\w*|moisi\w*|périmé\w*|honteux|n'importe quoi)\b", S),
    "urgent": re.compile(r"\b(?:urgent|urgence|au plus vite|tout de suite|catastrophe|panique|j'ai plus rien|en rupture chez moi|"
                         r"il me (?:faut|manque) .{0,25}pour ce soir|ce soir)\b", S),
    "confused": re.compile(r"(?:\bj'ai pas compris\b|\bje n'ai pas compris\b|\bvous pouvez répéter\b|\brépétez\b|^\s*(?:comment|pardon|hein)\s*\?)", S),
    "warm": re.compile(r"\b(?:merci beaucoup|merci infiniment|vous êtes (?:top|géniale?|super|adorable)|ça va (?:et )?vous \?|"
                       r"comment (?:allez-vous|ça va)|il fait (?:beau|froid)|bonne fête|bon week-end)\b", S),
}
SIGNALS = {
    "refusal": re.compile(r"\b(?:non merci|ça ira|ca ira|pas la peine|pas besoin|j'en veux pas|laisse(?:z)? tomber|on oublie)\b", S),
    "leaving": re.compile(r"\b(?:je vais réfléchir|je vais reflechir|je (?:vous|te) rappelle|je reviens vers|on verra|je vais voir)\b", S),
    "competitor": re.compile(r"\b(?:ailleurs|concurren\w*|chez (?:metro|promocash|transgourmet|un autre|l'autre)|moins cher chez|on me (?:le )?(?:fait|propose))\b", S),
    "best_price": re.compile(r"\b(?:meilleur prix|le mieux que vous|votre (?:meilleur|dernier) prix|vous (?:pouvez|pourriez) faire mieux|"
                             r"un meilleur prix|prix plus (?:bas|intéressant)|c'est (?:le|votre) mieux|y a moyen)\b", S),
    "price": re.compile(r"\b(?:(?:trop |un peu |vachement |assez )?cher|ça fait beaucoup|ca fait beaucoup|c'est beaucoup|un (?:petit )?(?:effort|geste)|une remise|un prix|"
                        r"(?:moins|mieux) que ça|négocier|negocier|hors budget|au-dessus de mon budget|dépasse mon budget|ça pique)\b", S),
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
    insults: int = 0
    off_topic: int = 0  # wrong number / prank turns


def signals(text: str) -> list[str]:
    found = [name for name, rx in {**SITUATIONS, **SIGNALS}.items() if rx.search(text or "")]
    if "insult" in found and "convinced" in found:
        found.remove("convinced")
    if "best_price" in found and "hesitant" in found:
        found.remove("hesitant")  # « Euh, c'est le meilleur prix ? » is a price question, the « euh » is just speech
    if "convinced" in found and any(s in found for s in ("price", "best_price", "competitor", "leaving", "refusal", "hesitant")):
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


def situation(state: Posture, sig: list[str]) -> dict | None:
    """Who/what before selling: insult, wrong number, prank, « are you a robot? », a human asked, anger, urgency,
    confusion, warmth. One stance; the emotion to show is part of it (never faked, never overdone)."""
    if "insult" in sig:
        state.insults += 1
        state.last = "insulte → calme" if state.insults == 1 else "insulte répétée → fin polie"
        if state.insults == 1:
            return {"stance": "calm_boundary", "emotion": "calme, posée",
                    "do": "Ne relève pas l'insulte et ne la répète pas. Une phrase calme qui pose le cadre sans reproche "
                          "(« Je sens que c'est une journée compliquée, je suis là pour vous aider. »), puis reviens à SA demande. Rien d'autre."}  # fmt: skip
        return {"stance": "polite_end", "emotion": "calme, ferme",
                "do": "Mets fin poliment : « Je préfère qu'on reprenne plus tard, quand ce sera plus calme. Bonne journée. » "
                      "Aucune commande, aucun argument, pas de reproche."}  # fmt: skip
    if "wrong_number" in sig:
        state.off_topic += 1
        state.last = "mauvais numéro → réoriente"
        return {"stance": "wrong_number", "emotion": "souriante, aidante",
                "do": "Il s'est sûrement trompé de numéro : dis-le gentiment (« Ah, ici c'est la Crèmerie des Aravis, le grossiste en fromages. ») "
                      "et souhaite-lui de trouver. S'il est commerçant, propose en une demi-phrase. Jamais de vente forcée, aucun outil."}  # fmt: skip
    if "prank" in sig:
        state.off_topic += 1
        state.last = "canular → humour léger"
        return {"stance": "prank", "emotion": "amusée, légère",
                "do": "Probable blague : réponds avec une pointe d'humour bienveillant en une phrase, puis vérifie sérieusement "
                      "(« Plus sérieusement, vous appelez pour quel établissement ? »). Aucune commande tant que ce n'est pas sérieux ; "
                      "deuxième fois : salue poliment et termine."}  # fmt: skip
    if "robot" in sig:
        state.last = "« vous êtes un robot ? » → honnête"
        return {"stance": "honest_ai", "emotion": "naturelle, souriante",
                "do": "Sois honnête, simplement : « Je suis l'assistante vocale de la Crèmerie des Aravis : je prends vos commandes, "
                      "et si vous préférez, un commercial vous rappelle. » Puis reprends où vous en étiez. Ne prétends jamais être humaine."}  # fmt: skip
    if "human" in sig:
        state.last = "demande un humain → rappel"
        return {"stance": "human_callback", "emotion": "serviable",
                "do": "Propose qu'un commercial le rappelle (aujourd'hui), demande le meilleur moment si besoin, et enregistre la demande "
                      "avec log_client_event (s'il est identifié). Ne promets pas d'heure précise. Propose quand même de prendre la commande tout de suite."}  # fmt: skip
    if "angry" in sig:
        state.last = "client mécontent → empathie d'abord"
        return {"stance": "empathy_first", "emotion": "sincèrement désolée, calme",
                "do": "D'abord l'empathie, vraie et courte (« Je suis vraiment désolée, je comprends que ça vous agace. »), puis UNE action concrète "
                      "(log_client_event pour la réclamation, avoir/remplacement selon la règle, qui le rappelle). Aucune vente dans ce tour. "
                      "Ne promets ni montant ni date que l'ERP ne donne pas."}  # fmt: skip
    if "urgent" in sig:
        state.last = "urgence → efficace"
        return {"stance": "urgent", "emotion": "rassurante, vive",
                "do": "Rassure en trois mots (« On va vous dépanner. »), puis va droit au but : produit, quantité, la livraison la plus proche "
                      "possible selon l'ERP. Phrases très courtes, aucun argument de vente."}  # fmt: skip
    if "confused" in sig:
        state.last = "n'a pas compris → plus simple"
        return {"stance": "rephrase", "emotion": "patiente",
                "do": "Redis la même chose plus simplement et plus court (une idée, des mots courants), sans « comme je disais »."}  # fmt: skip
    if "warm" in sig and not any(x in sig for x in ("price", "best_price", "competitor")):
        state.last = "chaleureux → répond avec le sourire"
        return {"stance": "warm", "emotion": "chaleureuse",
                "do": "Réponds avec le sourire, en quelques mots et naturellement (« Ça va très bien, merci ! »), puis reviens à la commande sans forcer."}  # fmt: skip
    return None


def coach(state: Posture, sig: list[str], args: dict | None) -> dict | None:
    """The stance for this turn (None: nothing special, the model answers normally)."""
    if not sig:
        return None
    if s := situation(state, sig):
        return s
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
    if "best_price" in sig and not state.discount_offered:
        # a direct question about the best price: show HOW to pay less (volume, short-dated lot), never « pas de remise »
        state.discount_offered = True
        state.last = "meilleur prix → options"
        return {"stance": "show_best_options",
                "do": "Réponds positivement en une demi-phrase (« C'est déjà votre tarif, mais on peut faire mieux selon la quantité. »), "
                      "puis appelle propose_deal (brouillon d'abord s'il n'existe pas) et dis son `say` : les options pour payer moins. "
                      "Jamais « pas de remise » ni « sans remise particulière »."}  # fmt: skip
    if "best_price" in sig:
        sig = [*sig, "price"]
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
            return {"stance": "justify_value", "use": a["facts"],
                    "do": "UNE phrase qui commence par « Je comprends, mais » suivi d'UN de ces faits et de ce qu'il apporte à ses clients, "
                          "puis UNE question qui vérifie si la valeur justifie le prix pour lui (« Pour vos clients, ça vaut la différence, non ? », "
                          "« C'est la qualité que vous cherchez ? »). Pendant une objection : JAMAIS « je vous les mets », « je valide », "
                          "ni autre produit ni remise à ce stade." + rival}  # fmt: skip
        if move == "reframe":
            pp = a["perPortion"]
            return {"stance": "reframe", "use": [f"{pp['price']} € la part de {pp['grams']} grammes"],
                    "do": "« Je comprends, mais » ramène le prix à la part (« ça fait … la part »), puis UNE question qui le fait raisonner "
                          "sur sa propre marge (« Vous la revendez combien, la part ? »). Pas de « je vous les mets », pas encore d'autre produit." + rival}  # fmt: skip
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
