from __future__ import annotations

import asyncio
import io
import logging
import os
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from hyprchan.core.extensions.executor import ExtensionExecutor
from hyprchan.core.extensions.extension import HyprchanExtension
from hyprchan.core.hypraios.hooks.types import HookResult


@dataclass(slots=True)
class VoiceConfig:
    sovits_url: str
    api_mode: str
    text_language: str
    prompt_text: str
    prompt_language: str
    reference_audio_path: str
    speed: float
    top_k: int
    top_p: float
    temperature: float
    request_timeout_sec: float
    middleware_enabled: bool
    middleware_api_url: str
    middleware_model: str
    middleware_api_key: str
    middleware_timeout_sec: float

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        openai_api_base = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
        middleware_url = os.getenv("HYPRSOVITS_MIDDLEWARE_API_URL", "").strip()
        if not middleware_url:
            middleware_url = openai_api_base

        middleware_model = os.getenv("HYPRSOVITS_MIDDLEWARE_MODEL", "").strip()
        if not middleware_model:
            middleware_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        middleware_key = os.getenv("HYPRSOVITS_MIDDLEWARE_API_KEY", "").strip()
        if not middleware_key:
            middleware_key = os.getenv(
                "OPENAI_OAUTH_TOKEN", os.getenv("OPENAI_API_KEY", "")
            ).strip()

        return cls(
            sovits_url=os.getenv("HYPRSOVITS_API_URL", "http://127.0.0.1:9880").strip(),
            api_mode=(
                os.getenv("HYPRSOVITS_API_MODE", "auto").strip().lower() or "auto"
            ),
            text_language=os.getenv("HYPRSOVITS_TEXT_LANGUAGE", "en").strip() or "en",
            prompt_text=os.getenv("HYPRSOVITS_PROMPT_TEXT", "").strip(),
            prompt_language=(
                os.getenv("HYPRSOVITS_PROMPT_LANGUAGE", "en").strip() or "en"
            ),
            reference_audio_path=(
                os.getenv(
                    "HYPRSOVITS_REFERENCE_WAV_PATH",
                    "/home/w/cutest-anime-girl-voice.mp3",
                ).strip()
            ),
            speed=float(os.getenv("HYPRSOVITS_SPEED", "1.0")),
            top_k=int(os.getenv("HYPRSOVITS_TOP_K", "20")),
            top_p=float(os.getenv("HYPRSOVITS_TOP_P", "0.6")),
            temperature=float(os.getenv("HYPRSOVITS_TEMPERATURE", "0.6")),
            request_timeout_sec=float(os.getenv("HYPRSOVITS_TIMEOUT_SEC", "35")),
            middleware_enabled=os.getenv("HYPRSOVITS_MIDDLEWARE_ENABLED", "1")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            middleware_api_url=middleware_url.rstrip("/"),
            middleware_model=middleware_model,
            middleware_api_key=middleware_key,
            middleware_timeout_sec=float(
                os.getenv("HYPRSOVITS_MIDDLEWARE_TIMEOUT_SEC", "8")
            ),
        )


class HyprSovitsExtension(HyprchanExtension):
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.config = VoiceConfig.from_env()
        self.enabled = os.getenv("HYPRSOVITS_ENABLED", "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._executor: ExtensionExecutor | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=16)
        self._worker_task: asyncio.Task[None] | None = None
        self._sovits_client: httpx.AsyncClient | None = None
        self._middleware_client: httpx.AsyncClient | None = None

    @property
    def executor(self) -> ExtensionExecutor:
        if self._executor is None:
            raise RuntimeError("Executor not initialized")
        return self._executor

    async def on_init(self, executor: ExtensionExecutor) -> None:
        self._executor = executor
        if not self.enabled:
            self.logger.info("[cyan]HYPRSOVITS[/] Disabled by HYPRSOVITS_ENABLED")
            return

        self._sovits_client = httpx.AsyncClient(
            timeout=self.config.request_timeout_sec,
            follow_redirects=True,
        )
        self._middleware_client = httpx.AsyncClient(
            timeout=self.config.middleware_timeout_sec,
            follow_redirects=True,
        )

        self.executor.add_hook("on_ai_response", self.on_ai_response, priority=50)  # pyright: ignore[reportArgumentType]
        self._worker_task = asyncio.create_task(self._speech_worker())
        ref_path = Path(self.config.reference_audio_path).expanduser()
        if not ref_path.exists():
            self.logger.warning(
                "[cyan]HYPRSOVITS[/] Reference voice file not found: %s",
                self.config.reference_audio_path,
            )
        self.logger.info(
            "[cyan]HYPRSOVITS[/] Ready. API=%s mode=%s ref=%s",
            self.config.sovits_url,
            self.config.api_mode,
            self.config.reference_audio_path,
        )

    async def on_shutdown(self) -> None:
        if self._executor is not None:
            self._executor.remove_hook("on_ai_response", self.on_ai_response)  # pyright: ignore[reportArgumentType]

        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._worker_task = None

        if self._sovits_client is not None:
            await self._sovits_client.aclose()
            self._sovits_client = None
        if self._middleware_client is not None:
            await self._middleware_client.aclose()
            self._middleware_client = None

    async def on_ai_response(self, payload: dict[str, object]) -> HookResult:
        if not self.enabled:
            return HookResult(payload=payload)

        mode = str(payload.get("mode", "")).strip().lower()
        if mode == "passive":
            return HookResult(payload=payload)

        response = payload.get("response")
        if not isinstance(response, dict):
            return HookResult(payload=payload)

        output = str(response.get("output", "")).strip()
        if not output:
            return HookResult(payload=payload)

        await self.executor.answer_user(output)  # pyright: ignore[reportAttributeAccessIssue]

        if self._queue.full():
            try:
                _ = self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                pass

        self._queue.put_nowait(output)
        return HookResult(payload=payload, stop=False)

    async def _speech_worker(self) -> None:
        while True:
            text = await self._queue.get()
            try:
                spoken = await self._pronunciation_middleware(text)
                wav_data = await self._synthesize(spoken)
                await asyncio.to_thread(self._play_wav, wav_data)
            except Exception as exc:
                self.logger.warning("[cyan]HYPRSOVITS[/] Speech failed: %s", exc)
            finally:
                self._queue.task_done()

    async def _pronunciation_middleware(self, text: str) -> str:
        if not self.config.middleware_enabled:
            return text
        if not self.config.middleware_api_key:
            return text
        client = self._middleware_client
        if client is None:
            return text

        url = f"{self.config.middleware_api_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.middleware_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.config.middleware_model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are pronunciation middleware for TTS. "
                        "Rewrite assistant text into naturally spoken form only. "
                        "Keep same language, style, and meaning. "
                        "Expand abbreviations, add punctuation for prosody, keep it concise. "
                        "Return only final spoken text."
                    ),
                },
                {"role": "user", "content": text},
            ],
        }

        try:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            self.logger.debug("[cyan]HYPRSOVITS[/] Middleware fallback: %s", exc)
            return text

        try:
            spoken = (
                payload.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
        except Exception:
            spoken = ""
        return spoken or text

    async def _synthesize(self, text: str) -> bytes:
        client = self._sovits_client
        if client is None:
            raise RuntimeError("Sovits client not initialized")

        mode = self.config.api_mode
        if mode not in {"auto", "v1", "v2"}:
            mode = "auto"

        start = time.monotonic()
        response: httpx.Response | None = None
        if mode in {"auto", "v2"}:
            response = await self._synthesize_v2(client, text)
            if response.status_code < 400:
                elapsed = (time.monotonic() - start) * 1000.0
                self.logger.debug(
                    "[cyan]HYPRSOVITS[/] Synthesized v2 in %.1fms (%d bytes)",
                    elapsed,
                    len(response.content),
                )
                return bytes(response.content)
            if mode == "v2":
                detail = response.text.strip()
                raise RuntimeError(
                    f"GPT-SoVITS v2 HTTP {response.status_code}: {detail or 'request failed'}"
                )

        response = await self._synthesize_v1(client, text)
        elapsed = (time.monotonic() - start) * 1000.0

        if response.status_code >= 400:
            detail = response.text.strip()
            raise RuntimeError(
                f"GPT-SoVITS v1 HTTP {response.status_code}: {detail or 'request failed'}"
            )

        self.logger.debug(
            "[cyan]HYPRSOVITS[/] Synthesized v1 in %.1fms (%d bytes)",
            elapsed,
            len(response.content),
        )
        return bytes(response.content)

    async def _synthesize_v2(
        self, client: httpx.AsyncClient, text: str
    ) -> httpx.Response:
        payload: dict[str, Any] = {
            "text": text,
            "text_lang": self.config.text_language,
            "ref_audio_path": self.config.reference_audio_path,
            "prompt_lang": self.config.prompt_language,
            "prompt_text": self.config.prompt_text,
            "top_k": self.config.top_k,
            "top_p": self.config.top_p,
            "temperature": self.config.temperature,
            "speed_factor": self.config.speed,
            "media_type": "wav",
            "streaming_mode": False,
        }
        return await client.post(
            f"{self.config.sovits_url.rstrip('/')}/tts", json=payload
        )

    async def _synthesize_v1(
        self, client: httpx.AsyncClient, text: str
    ) -> httpx.Response:
        payload: dict[str, Any] = {
            "refer_wav_path": self.config.reference_audio_path,
            "prompt_text": self.config.prompt_text,
            "prompt_language": self.config.prompt_language,
            "text": text,
            "text_language": self.config.text_language,
            "top_k": self.config.top_k,
            "top_p": self.config.top_p,
            "temperature": self.config.temperature,
            "speed": self.config.speed,
        }
        return await client.post(self.config.sovits_url, json=payload)

    def _play_wav(self, wav_data: bytes) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except Exception as exc:
            self._dump_failed_audio(wav_data)
            raise RuntimeError(f"sounddevice unavailable: {exc}") from exc

        with wave.open(io.BytesIO(wav_data), "rb") as wav_file:
            frame_rate = int(wav_file.getframerate())
            channels = int(wav_file.getnchannels())
            sample_width = int(wav_file.getsampwidth())
            raw = wav_file.readframes(wav_file.getnframes())

        if sample_width == 1:
            audio = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
            audio = (audio - 128.0) / 128.0
        elif sample_width == 2:
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            self._dump_failed_audio(wav_data)
            raise RuntimeError(f"Unsupported sample width: {sample_width}")

        if channels > 1:
            audio = audio.reshape(-1, channels)

        sd.play(audio, samplerate=frame_rate, blocking=True)
        sd.wait()

    def _dump_failed_audio(self, wav_data: bytes) -> None:
        base_dir = self.data_dir if isinstance(self.data_dir, Path) else Path.cwd()
        out_dir = base_dir / "failed_audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"hyprsovits_failed_{int(time.time() * 1000)}.wav"
        target.write_bytes(wav_data)
