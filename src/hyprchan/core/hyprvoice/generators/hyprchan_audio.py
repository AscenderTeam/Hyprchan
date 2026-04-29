import io

import aiohttp

from hyprchan.core.hyprvoice.generator import VoiceGenerator
from hyprchan.core.hyprvoice.utils import get_reference_text, get_sample_voice_path


class HyprchanAudioGenerator(VoiceGenerator):
    name: str = "hyprchan_audio"

    def __init__(self, url: str, token: str) -> None:
        self.sample_voice = get_sample_voice_path()
        self.ref_text = get_reference_text()
        self.url = url
        self.token = token

    async def generate(self, text: str) -> io.BytesIO:
        """Returns raw WAV bytes in a BytesIO buffer — no disk I/O."""
        with open(self.sample_voice, "rb") as f:
            audio_bytes = f.read()

        form = aiohttp.FormData()
        form.add_field("text", text)
        if self.ref_text:
            form.add_field("ref_text", self.ref_text)
        form.add_field(
            "ref_audio",
            io.BytesIO(audio_bytes),
            filename="ref_audio.mp3",
            content_type="audio/mpeg",
        )

        timeout = aiohttp.ClientTimeout(total=120, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self.url, headers={"Authorization": f"Bearer {self.token}"}, data=form
            ) as resp:
                resp.raise_for_status()
                buf = io.BytesIO(await resp.read())
                buf.seek(0)
                return buf

    async def stream(self, text: str):
        raise NotImplementedError("Hyprchan Audio doesn't support streaming for now...")

    async def stop(self) -> None:
        pass  # HTTP requests are fire-and-forget; nothing to cancel here
