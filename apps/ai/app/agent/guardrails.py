"""Deterministic protection against accidental order confirmation."""
import re

from app.schemas import ChatMessage

# The assistant may never use a tool call as evidence of customer consent.
# French phone talk: « ouais vas-y », « ça marche », « nickel », « c'est tout bon », « banco »…
AFFIRMATIVE = re.compile(
    r"\b(oui|ouais|ouep|yes|ok|okay|d'accord|d accord|dac|je confirme|c'est bon|c est bon|c'est tout bon|c'est parfait|c'est ça|"
    r"c est ça|valide[sz]?|confirme[sz]?|vas[- ]y|allez[- ]y|go|ça marche|ca marche|ça me va|ca me va|parfait|nickel|impeccable|"
    r"très bien|tres bien|exactement|banco|envoie|tope là|confirm|go ahead)\b",
    re.I,
)
NEGATIVE = re.compile(r"\b(non|pas encore|attend[sz]?|annule[sz]?|ne confirme pas|don't|do not|not yet|no)\b", re.I)
# In a conversation, « oui mais enlève le beurre » is a correction, not an approval of the recap: apply it, recap
# again, ask again. (Not in command mode, where « ajoute deux reblochons et confirme la commande » is one order.)
CORRECTION = re.compile(
    r"\b(mais|sauf|plutôt|plutot|enl[eè]ve[sz]?|retire[sz]?|rajoute[sz]?|ajoute[sz]?|change[sz]?|remplace[sz]?)\b", re.I
)
ORDER_RECAP = re.compile(r"\b(command[ea]|order|récapitulatif|recap|total|brouillon|draft|livraison|je valide|je (?:vous |te )?réserve)\b", re.I)


def may_confirm(messages: list[ChatMessage], mode: str) -> bool:
    """Require an explicit customer yes AFTER an assistant order recap.

    Command mode permits an unambiguous explicit imperative, but not a generic yes.
    """
    user_indices = [i for i, m in enumerate(messages) if m.role == "user"]
    if not user_indices:
        return False
    idx = user_indices[-1]
    utterance = messages[idx].content or ""
    if not isinstance(utterance, str) or NEGATIVE.search(utterance):
        return False
    if mode == "command":
        return bool(re.search(r"\b(confirme[sz]?|valide[sz]?|confirm)\b.{0,60}\b(command[ea]|order|brouillon|draft)\b", utterance, re.I))
    if not AFFIRMATIVE.search(utterance) or CORRECTION.search(utterance):
        return False
    # A yes alone is not sufficient: the assistant must have previously read back the order.
    return any(m.role == "assistant" and isinstance(m.content, str) and ORDER_RECAP.search(m.content)
               for m in messages[:idx][-8:])


def is_mutation(name: str) -> bool:
    return name.startswith(("create_", "add_", "confirm_", "save_", "log_", "update_", "delete_", "cancel_", "remove_"))
