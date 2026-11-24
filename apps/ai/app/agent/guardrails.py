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
ORDER_RECAP = re.compile(r"\b(command[ea]|order|récapitulatif|recap|total|brouillon|draft|livraison|je valide)\b", re.I)


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
    if mode == "voice":
        return _voice_recap_answered(messages, idx)
    # A yes alone is not sufficient: the assistant must have previously read back the order.
    return any(m.role == "assistant" and isinstance(m.content, str) and ORDER_RECAP.search(m.content)
               for m in messages[:idx][-8:])


def is_mutation(name: str) -> bool:
    return name.startswith(("create_", "add_", "confirm_", "save_", "log_", "update_", "delete_", "cancel_", "remove_"))


# ── voice: the yes must answer the LATEST recap, heard in full, whose only question was the confirmation ──

CONFIRM_QUESTION = re.compile(r"\b(valide|confirme|réserve|reserve|c'est bon|on y va|ça vous va|ça te va|on part là-dessus|je lance)\b", re.I)
OTHER_QUESTION = re.compile(r"\b(combien|quel|quelle|quels|quelles|lequel|laquelle|où|quand|comment|ou (?:le|la|les|du|de la|des))\b|\ben même temps\b", re.I)
ORDER_WRITES = {"create_draft_order", "add_order_line", "update_order_line", "remove_order_line", "update_order"}
_NOTES = re.compile(r"\[[^\]]*\]")


def _voice_recap_answered(messages: list[ChatMessage], idx: int) -> bool:
    """« Oui » confirms only if the last thing the agent said (before this yes) was an order recap that
    - asked ONE question, the confirmation (« Combien ? Et je valide ? » → the yes is ambiguous),
    - was not cut by the caller (« … (interrompu) »: the essentials may not have been heard),
    - is still the current version: no order write after it (a change since → a new recap is needed)."""
    recap_at = None
    for i in range(idx - 1, -1, -1):
        m = messages[i]
        if m.role == "assistant" and isinstance(m.content, str) and _NOTES.sub("", m.content).strip():
            recap_at = i
            break
    if recap_at is None:
        return False
    text = _NOTES.sub("", messages[recap_at].content).strip()
    if "(interrompu" in text or text.endswith("…") or not ORDER_RECAP.search(text):
        return False
    questions = [q for q in re.split(r"(?<=[?])\s*|(?<=[.!])\s+", text) if q.strip().endswith("?")]
    if len(questions) != 1 or not CONFIRM_QUESTION.search(questions[0]) or OTHER_QUESTION.search(questions[0]):
        return False  # « Il vous en faut combien, et je valide la tomme ? » → which one did « oui » answer?
    for m in messages[recap_at + 1 : idx]:  # the recap's own write (same message) is the version it describes
        if m.role == "assistant" and any(c.name in ORDER_WRITES for c in m.tool_calls or []):
            return False
    return True
