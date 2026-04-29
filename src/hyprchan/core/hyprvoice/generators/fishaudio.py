from __future__ import annotations

import io

import aiohttp

from hyprchan.core.hyprvoice.generator import VoiceGenerator
from hyprchan.core.hyprvoice.utils import get_reference_text, get_sample_voice_path


class FishAudioGenerator(VoiceGenerator):
    name: str = "fishaudio"

    def __init__(self, token: str, url: str = "https://api.fish.audio/v1/tts") -> None:
        self.token = token
        self.url = url
        self._sample_voice = get_sample_voice_path()
        self._ref_text = get_reference_text() or ""

    async def generate(self, text: str) -> io.BytesIO:
        with open(self._sample_voice, "rb") as f:
            audio_bytes = f.read()

        payload = {
            "text": text,
            "format": "wav",
            "latency": "normal",
            "references": [
                {
                    "audio": list(audio_bytes),
                    "text": self._ref_text,
                }
            ],
        }

        timeout = aiohttp.ClientTimeout(total=120, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self.url,
                headers={"Authorization": f"Bearer {self.token}"},
                json=payload,
            ) as resp:
                resp.raise_for_status()
                buf = io.BytesIO(await resp.read())
                buf.seek(0)
                return buf

    async def stream(self, text: str) -> io.BytesIO:
        raise NotImplementedError

    async def stop(self) -> None:
        pass
