"""
What of the model's text the CALLER may hear and see (voice only). Three kinds of output, separated by structure first:

    INTERNAL  the model's notes: anything [between brackets] (the voice prompt's channel for thinking in writing),
              and the text of a step that ends in a READ tool call (« Je vérifie le reblochon. » → find_product):
              that text was the model talking to itself before looking something up
    TOOL      calls, arguments, results: never text (AgentToolMessage, logs)
    CUSTOMER  everything else: the answer, the recap said just before a write, the alerts

The step structure is only known when the step ends, so a sentence is held until it is safe: released at once when it
is a question (a question is for the caller), when another sentence follows it (the model is answering, not
announcing a lookup), at a write tool call (the recap before create_draft_order) or at the end of the answer. Held
text of a step that calls a read tool is dropped. Then the deterministic filters (Speaker: META_TALK, English asides)
still apply sentence by sentence. No second model call, and the answer still streams sentence by sentence.
"""

import re

# a sentence ends with . ! ? … followed by a space ("18.50" is not a boundary)
_END = re.compile(r"[.!…](?=\s)|\?(?=\s|$)")  # a question mark at the end of the stream so far: a full question
_BRACKETS = re.compile(r"\[[^\]]*\]")
GREETING = re.compile(r"\s*(?:bonjour|bonsoir|salut|allô|allo|hello)\b[^.?!]{0,30}[!.]\s*", re.IGNORECASE)

# The step starts like an answer to the caller (a quantity, a price, a yes / no): stream it clause by clause, no wait.
CUSTOMER_OPENER = re.compile(
    r"^\s*(?:\d|(?:un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingt|"
    r"trente|quarante|cinquante|soixante|cent|mille|demi)\b|pour vous\b|oui\b|non\b|ça marche|parfait|d'accord|"
    r"le fermier|la tomme|le reblochon|on n'en a|désolée?\b)",
    re.IGNORECASE,
)
# A sentence that says an ERP write went through: never said before the write's result came back ok.
SUCCESS_CLAIM = re.compile(
    r"\bc'est (?:bien )?(?:validé|confirmé|ajouté|enregistré|noté|fait|retiré|modifié|annulé|commandé|réservé)\b|"
    r"\bje (?:confirme|valide)\b(?![^.!?]*\?)|\b(?:commande|ligne) (?:validée|confirmée|créée|ajoutée|modifiée)\b",
    re.IGNORECASE,
)

# Tools that change the ERP: the text before them is the recap the caller must hear (VOICE_RULES).
WRITE_TOOLS = {"create_draft_order", "add_order_line", "update_order_line", "remove_order_line", "update_order",
               "confirm_order", "cancel_order", "create_supplier_orders", "log_client_event"}  # fmt: skip


class CustomerGate:
    def __init__(self) -> None:
        self.raw = ""  # this step's text not yet decided (brackets included)
        self.released_any = False  # something was released in this turn
        self.internal: list[str] = []  # dropped as INTERNAL, for the logs / diagnosis
        self.step_customer: bool | None = None  # this step opened like an answer to the caller (decided on 2+ words)
        self.write_ok = False  # an ERP write of this turn came back ok: success sentences may be said
        self.pending = ""  # a success sentence (and what follows it) waiting for the write's result
        self.write_attempted = False  # a write tool was called this turn

    # ── input ──

    def push(self, delta: str) -> str:
        """New model text. Returns the part that may be said now ('' if it must wait)."""
        self.raw += delta
        return self._release(final=False)

    def tool_call(self, name: str) -> str:
        """The step ends in a tool call: its text is the recap (write) → released, or a preamble (read) → dropped."""
        self.step_customer = None  # the next step decides again
        if name in WRITE_TOOLS:
            self.write_attempted = True
            return self._release(final=True)
        return self._drop()

    def write_succeeded(self) -> str:
        """An ERP write came back ok: the held success sentence can be said now."""
        self.write_ok = True
        out, self.pending = self.pending, ""
        return out

    def write_failed(self) -> None:
        """The write failed: « c'est validé » would be false. Dropped; the model explains the consequence."""
        self.failed = True
        if self.pending.strip():
            self.internal.append(self.pending.strip())
        self.pending = ""

    def finish(self) -> str:
        """End of the answer: what is left is said (a success sentence never confirmed by the ERP is not)."""
        out = self._release(final=True)
        if self.pending.strip() and not self.write_ok and (self.write_attempted or getattr(self, "failed", False)):
            self.internal.append(self.pending.strip())  # a write was tried and did not go through
        elif self.pending:  # ok write, or no write at all this turn (« C'est noté. » about what was said)
            out += self.pending
        self.pending = ""
        return out

    # ── internals ──

    def _visible(self) -> tuple[str, int]:
        """(text without the bracketed notes, how much of `raw` it covers). An open '[' holds everything after it."""
        cut = len(self.raw)
        if (opened := self.raw.rfind("[")) > self.raw.rfind("]"):
            cut = opened
        head = self.raw[:cut]
        notes = _BRACKETS.findall(head)
        if notes:
            self.internal += [n.strip("[] ") for n in notes if n.strip("[] ")]
        return _BRACKETS.sub("", head), cut

    def _release(self, final: bool) -> str:
        visible, cut = self._visible()
        if final:
            out = visible  # an unclosed « [note » after `cut` is never said
            self.raw = ""
        elif self._customer_step(visible):
            # an answer to the caller: everything up to the last sentence end, or a clause once it is long enough
            bounds = [m.end() for m in _END.finditer(visible)] + [m.end() for m in re.finditer(r"[,;:](?=\s)", visible) if m.end() >= 28]
            if not bounds:
                self._keep_notes_only(visible, cut)
                return ""
            upto = max(bounds)
            while upto < len(visible) and visible[upto].isspace():
                upto += 1
            out = visible[:upto]
            self.raw = visible[upto:] + self.raw[cut:]
        else:
            ends = [m.end() for m in _END.finditer(visible)]
            if not ends:
                self._keep_notes_only(visible, cut)
                return ""
            # release up to the last question mark, or up to the last complete sentence that text follows (the
            # model went on: it is answering, not announcing a lookup). A lone finished sentence waits.
            questions = [e for e in ends if visible[e - 1] == "?"]
            followed = [e for e in ends if visible[e:].strip()]
            upto = max(questions[-1] if questions else 0, followed[-1] if followed else 0)
            if not upto:
                self._keep_notes_only(visible, cut)
                return ""
            while upto < len(visible) and visible[upto].isspace():  # the Speaker cuts sentences at « . » + space
                upto += 1
            out = visible[:upto]
            self.raw = visible[upto:] + self.raw[cut:]
        out = self._hold_claims(re.sub(r"[ \t]{2,}", " ", out))
        if out.strip():
            self.released_any = True
        return out

    def _customer_step(self, visible: str) -> bool:
        if self.step_customer is None and len(visible.split()) >= 2:
            self.step_customer = bool(CUSTOMER_OPENER.match(visible))
        return bool(self.step_customer)

    def _hold_claims(self, out: str) -> str:
        """From the first « c'est validé / ajouté… » not yet backed by an ok write, everything waits (order kept)."""
        if self.write_ok:
            return out
        if self.pending:
            self.pending += out
            return ""
        for m in re.finditer(r"[^.!?…]*[.!?…]?\s*", out):
            if m.group(0).strip() and SUCCESS_CLAIM.search(m.group(0)):
                self.pending = out[m.start() :]
                return out[: m.start()]
        return out

    def _keep_notes_only(self, visible: str, cut: int) -> None:
        """Nothing released: keep the visible text + any open note, the closed notes are already logged."""
        self.raw = visible + self.raw[cut:]

    def _drop(self) -> str:
        """Before a read: only a greeting survives (« Bonjour Jean-Marc ! », said as a person picking up)."""
        visible, _ = self._visible()
        self.raw = ""
        greeting = GREETING.match(visible)
        rest = visible[greeting.end() :] if greeting else visible
        if rest.strip():
            self.internal.append(rest.strip())
        if greeting:
            self.released_any = True
            return greeting.group(0)
        return ""
