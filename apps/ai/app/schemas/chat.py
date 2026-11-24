"""
Chat contract: the conversation format and the events streamed by POST /chat.

POST /chat   body ChatRequest → text/event-stream, one ChatStreamEvent JSON per `data:` line.
The agent loop (app/agent/loop.py) yields exactly these events.
"""

from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .base import WireModel

ChatRole = Literal["system", "user", "assistant", "tool"]
ChatMode = Literal["chat", "voice", "command"]


class ToolCall(WireModel):
    """The model asks to run a tool."""

    id: str
    name: str
    arguments: dict[str, Any] = {}


class ChatMessage(WireModel):
    role: ChatRole
    content: str = ""
    tool_call_id: str | None = None  # for role "tool": which call this result answers
    tool_calls: list[ToolCall] | None = None  # for role "assistant": the tools it asked for
    name: str | None = None  # for role "tool": the tool's name


class ToolInfo(WireModel):
    """What the model sees of a tool (GET /tools)."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(description="JSON schema of the arguments")


class ChatRequest(WireModel):
    messages: list[ChatMessage] = Field(description="Full conversation so far (no system message: the harness adds it)")
    mode: ChatMode | None = Field(
        None, description="voice → short spoken-style answers; command → single-turn, act-first, one line"
    )
    actor_name: str | None = None


class Usage(WireModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None  # Anthropic prompt cache: tokens written this turn
    cache_read_input_tokens: int | None = None  # Anthropic prompt cache: tokens read (hits) this turn


class ToolTiming(WireModel):
    """One tool call of the turn (run by the model or preloaded by a fast path)."""

    name: str
    start_ms: int = Field(description="End of caller speech → tool started")
    ms: int = Field(description="Tool duration")


class TurnTimings(WireModel):
    """Latency breakdown of one turn, in milliseconds. Unless said otherwise, every *_ms counts from the END of the
    caller's speech as the server sees it (audio_end received, or the typed text received)."""

    stt_ms: int | None = Field(None, description="End of speech → final transcript (live finalize, or the fallback)")
    llm_first_token_ms: int | None = Field(None, description="Model call start → first model output (text or tool call)")
    llm_total_ms: int | None = None
    llm_model: str | None = Field(None, description="Model that answered this turn (services/model_router.py), with why")
    llm_usage: Usage | None = Field(None, description="Tokens of this turn's model calls (cost per call)")
    tts_first_byte_ms: int | None = None
    total_ms: int | None = Field(None, description="End of caller speech → first agent audio byte (acknowledgement included)")
    # ── diagnosis (latency task 1) ──
    stt_connect_ms: int | None = Field(None, description="START of speech → live STT stream ready (vocabulary + connection)")
    stt_backlog_frames: int | None = Field(None, description="Audio frames not yet sent to the STT when the speech ended")
    stt_finalize_sent_ms: int | None = Field(None, description="End of speech → all audio sent + finalize request sent")
    stt_fallback: bool | None = Field(None, description="True: the live stream failed, the whole recording was re-transcribed")
    ack_audio_ms: int | None = Field(None, description="End of speech → first acknowledgement / filler audio byte sent")
    useful_text_ms: int | None = Field(None, description="End of speech → first word of the real answer (not a filler)")
    useful_audio_ms: int | None = Field(None, description="End of speech → first audio byte of the real answer sent")
    tools: list[ToolTiming] | None = None


# ── Stream events ──


class TextEvent(WireModel):
    type: Literal["text"] = "text"
    delta: str


class ToolCallEvent(WireModel):
    type: Literal["tool_call"] = "tool_call"
    call: ToolCall


class ToolResultEvent(WireModel):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    name: str
    ok: bool
    result: Any
    ms: int


class DoneEvent(WireModel):
    type: Literal["done"] = "done"
    message: ChatMessage
    usage: Usage | None = None
    ms: int
    timings: TurnTimings | None = None


class ErrorEvent(WireModel):
    type: Literal["error"] = "error"
    message: str


ChatStreamEvent = Annotated[
    Union[TextEvent, ToolCallEvent, ToolResultEvent, DoneEvent, ErrorEvent],
    Field(discriminator="type"),
]
