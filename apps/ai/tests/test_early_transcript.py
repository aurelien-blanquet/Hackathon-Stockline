"""Early start: the turn starts on the settled live text; writes wait for the final words; a different final restarts."""

import asyncio

from app.clients.base import STTClient, STTUpdate
from app.services import utterance as utt
from app.services.voice_session import same_words, writes_after
from app.tools.registry import Tool, ToolArgs


class SlowFinalSTT(STTClient):
    """Live text settles at once; the provider's final words come 1 s after the end of audio."""

    name, streams = "fake", True

    def __init__(self, final: str = "vingt reblochons pour samedi"):
        self.final_text = final

    async def transcribe(self, audio, mime, hint=None):
        return self.final_text

    async def transcribe_stream(self, audio, mime, hint=None):
        yield STTUpdate("vingt reblochons pour samedi", stable="vingt reblochons")
        async for _ in audio:
            pass
        await asyncio.sleep(1.0)
        yield STTUpdate(self.final_text, final=True, stable=self.final_text)


async def _partial(_):
    pass


async def test_turn_starts_on_the_settled_text_long_before_the_final(monkeypatch):
    async def no_hint(*a, **k):
        return None

    monkeypatch.setattr(utt, "stt_hint", no_hint)
    u = utt.Utterance(SlowFinalSTT(), "audio/webm", None, _partial)
    u.feed(b"x")
    await asyncio.sleep(0.35)  # the caller spoke; the live text stopped changing
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    text, early = await u.early_text()
    assert early and text == "vingt reblochons pour samedi" and loop.time() - t0 < 0.2
    assert await u.final() == "vingt reblochons pour samedi"


def test_same_words_ignores_case_and_punctuation():
    assert same_words("Vingt reblochons, pour samedi.", "vingt reblochons pour samedi")
    assert not same_words("vingt reblochons pour samedi", "trente reblochons pour samedi")


async def test_writes_wait_for_the_final_words_reads_do_not():
    done: list[str] = []

    async def read(ctx):
        done.append("read")

    async def write(ctx):
        done.append("write")

    tools = [Tool(name="find_product", description="", args_model=ToolArgs, fn=read),
             Tool(name="create_draft_order", description="", args_model=ToolArgs, fn=write)]  # fmt: skip
    ok = asyncio.get_running_loop().create_future()
    gated = {t.name: t for t in writes_after(tools, ok)}
    await gated["find_product"].fn(None)
    pending = asyncio.ensure_future(gated["create_draft_order"].fn(None))
    await asyncio.sleep(0.05)
    assert done == ["read"]  # the write waits
    ok.set_result(True)
    await pending
    assert done == ["read", "write"]


async def test_a_corrected_transcript_cancels_the_write():
    async def write(ctx):
        raise AssertionError("must not write")

    ok = asyncio.get_running_loop().create_future()
    (gated,) = writes_after([Tool(name="confirm_order", description="", args_model=ToolArgs, fn=write)], ok)
    ok.set_result(False)
    try:
        await gated.fn(None)
        raise AssertionError("should be cancelled")
    except asyncio.CancelledError:
        pass
