"""ElevenLabs TTS, streaming endpoint: POST /v1/text-to-speech/{voice}/stream → mp3 chunks (audio/mpeg)."""

import httpx

from .base import TTSClient, TTSResult
from .http import body_chunks, http_client, post_stream


class ElevenLabsTTS(TTSClient):
    name = "elevenlabs"

    def __init__(
        self,
        api_key: str,
        model: str = "eleven_flash_v2_5",  # ~100 ms, French OK, cheapest; eleven_v4_turbo = same latency, more expressive
        voice: str = "JBFqnCBsd6RMkjVDRZzb",  # a premade multilingual voice; pick a French one in your ElevenLabs library
        language: str = "fr",
        http: httpx.AsyncClient | None = None,
        voice_settings: dict | None = None,  # ElevenLabs voice_settings: stability, similarity_boost, style, speed…
    ):
        self.api_key, self.model, self.voice, self.language, self.http = api_key, model, voice, language, http
        self.voice_settings = voice_settings

    def build_body(self, text: str, previous_text: str | None = None, next_text: str | None = None) -> dict:
        body = {"text": text, "model_id": self.model}
        if previous_text:  # the intonation continues from the sentence before instead of restarting (no choppy reply)
            body["previous_text"] = previous_text[-300:]
        if next_text:
            body["next_text"] = next_text[:300]
        if "multilingual_v2" not in self.model:  # language_code is refused by eleven_multilingual_v2
            body["language_code"] = self.language
        if self.voice_settings:
            body["voice_settings"] = self.voice_settings
        return body

    async def synthesize(self, text: str, voice: str | None = None, previous_text: str | None = None,
                         next_text: str | None = None) -> TTSResult:
        res = await post_stream(
            self.http or http_client(),
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice or self.voice}/stream?output_format=mp3_44100_128",
            who="elevenlabs tts",
            headers={"xi-api-key": self.api_key},
            json=self.build_body(text, previous_text, next_text),
        )
        return TTSResult("audio/mpeg", body_chunks(res))
