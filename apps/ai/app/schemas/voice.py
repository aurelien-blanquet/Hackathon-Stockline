"""
WS /voice contract: push-to-talk sessions, two tracks (the human "caller" and the agent).

Client → server: JSON messages below, plus binary audio frames between audio_start and audio_end.
Server → client: JSON messages below, plus binary audio frames between agent_audio_start and agent_audio_end.
"""

from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .base import WireModel
from .chat import TurnTimings

# ── Client → server ──


class StartMessage(WireModel):
    """Opens a conversation (same sessionId again = keep the history)."""

    type: Literal["start"] = "start"
    session_id: str | None = None
    actor_name: str | None = None


class AudioStartMessage(WireModel):
    """Caller pressed the talk key; binary frames follow."""

    type: Literal["audio_start"] = "audio_start"
    mime: str
    hint: str | None = None  # optional STT hint (vocabulary; mock STT: the transcript), like x-mock-text on POST /command


class AudioEndMessage(WireModel):
    """Caller released the key: the frames received since audio_start are the utterance (already streamed to the
    STT as they arrived: send them every 100–250 ms, e.g. MediaRecorder.start(100))."""

    type: Literal["audio_end"] = "audio_end"


class TextMessage(WireModel):
    """Typed instead of spoken (debug)."""

    type: Literal["text"] = "text"
    text: str


class ResetMessage(WireModel):
    type: Literal["reset"] = "reset"


VoiceClientMessage = Annotated[
    Union[StartMessage, AudioStartMessage, AudioEndMessage, TextMessage, ResetMessage],
    Field(discriminator="type"),
]

# ── Server → client ──


class ReadyMessage(WireModel):
    type: Literal["ready"] = "ready"
    session_id: str
    stt: str
    tts: str
    llm: str


class TranscriptMessage(WireModel):
    """What the caller said. While they speak (streaming STT): final=false, the whole text heard so far, sent again
    as words are recognised; `stable` is its leading part made of final words (will not change, the rest may).
    Then once final=true with the definitive text, which the agent answers."""

    type: Literal["transcript"] = "transcript"
    track: Literal["caller"] = "caller"
    text: str
    final: bool
    stable: str | None = None


class AgentTextMessage(WireModel):
    type: Literal["agent_text"] = "agent_text"
    delta: str


class AgentToolMessage(WireModel):
    """Sent twice per tool: once with `args` when called, once with `ok`/`ms` when done."""

    type: Literal["agent_tool"] = "agent_tool"
    name: str
    ok: bool | None = None
    ms: int | None = None
    args: dict[str, Any] | None = None


class AgentStatusMessage(WireModel):
    """What the side agents are doing, for the caller's screen (« Recherche des offres… », « Meilleure offre trouvée. »)."""

    type: Literal["agent_status"] = "agent_status"
    label: str


class OfferChoice(WireModel):
    """One possibility for a product the stock cannot fully cover: our stock, a producer's own offer, or a similar
    product in stock. The producer's NAME is shown (provenance), never its purchase price, the cost or the margin."""

    kind: str  # stock | producer | alternative
    label: str  # « Notre stock », « Coopérative Fruitière du Val des Aravis », « Raclette de Savoie IGP »
    qty: float | None = None
    unit: str | None = None
    unit_price: float | None = None  # the CALLER's price for this option
    delivery: str | None = None  # « demain (mercredi 25 novembre) », « arrivée jeudi 26 novembre »
    in_time: bool = True
    best: bool = False  # the market's pick


class OfferLine(WireModel):
    """One product of the offer card. Customer-facing only: no cost, no margin, no internal id (producers appear only
    as provenance in `choices`)."""

    product: str
    qty: float | None = None  # None: the caller has not said how much yet
    unit: str | None = None  # kg, piece, box, liter, dozen
    unit_price: float | None = None  # the caller's own price (price list or negotiated client price), EUR excl. VAT
    total: float | None = None
    availability: str  # « En stock », « 851 en stock, le reste arrive jeudi », « À préciser »
    delivery: str | None = None  # « mercredi 25 novembre »
    options: list[str] | None = None  # the variants to choose from when the product is ambiguous
    choices: list[OfferChoice] | None = None  # every possibility when the stock is short (stock, each producer, similar)


class CustomerMessage(WireModel):
    """The written recap sent to the customer the moment the order is confirmed (tools/orders.py send_recap)."""

    type: Literal["customer_message"] = "customer_message"
    channel: str  # sms | whatsapp | email
    to: str  # contact name · number or address
    text: str


class AgentOfferMessage(WireModel):
    """The best offer found for this turn (replaces the previous card)."""

    type: Literal["agent_offer"] = "agent_offer"
    lines: list[OfferLine]


class AgentDealMessage(WireModel):
    """« Le comité de prix » on the staff screen: the four agents' findings, the options with margins, the decision.
    `panel` is None while the agents work (show them working). Never read to the caller."""

    type: Literal["agent_deal"] = "agent_deal"
    panel: dict[str, Any] | None = None


class AgentAudioStartMessage(WireModel):
    """Binary audio frames follow (one segment per turn)."""

    type: Literal["agent_audio_start"] = "agent_audio_start"
    mime: str


class AgentAudioMarkMessage(WireModel):
    """Inside the audio segment: the next audio bytes are the real answer (what came before was an acknowledgement
    or a filler). Lets the browser measure when the useful answer is actually heard."""

    type: Literal["agent_audio_mark"] = "agent_audio_mark"
    kind: Literal["useful"] = "useful"


class AgentAudioEndMessage(WireModel):
    type: Literal["agent_audio_end"] = "agent_audio_end"


class AgentDoneMessage(WireModel):
    type: Literal["agent_done"] = "agent_done"
    text: str
    timings: TurnTimings


class VoiceErrorMessage(WireModel):
    type: Literal["error"] = "error"
    message: str


VoiceServerMessage = Annotated[
    Union[
        ReadyMessage,
        TranscriptMessage,
        AgentTextMessage,
        AgentToolMessage,
        AgentStatusMessage,
        CustomerMessage,
        AgentOfferMessage,
        AgentDealMessage,
        AgentAudioStartMessage,
        AgentAudioMarkMessage,
        AgentAudioEndMessage,
        AgentDoneMessage,
        VoiceErrorMessage,
    ],
    Field(discriminator="type"),
]
