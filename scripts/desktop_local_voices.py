"""Local synthesis providers, isolated from GUI and playback scheduling."""
from dataclasses import dataclass
from html import escape
import json
import os
from pathlib import Path


def onnx_options(threads):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return options


def load_voice(path, threads=4):
    """Keep the small Piper path available for latency comparisons."""
    import onnxruntime as ort
    from piper import PiperVoice
    from piper.config import PiperConfig
    return PiperVoice(session=ort.InferenceSession(str(path), sess_options=onnx_options(threads),
                      providers=["CPUExecutionProvider"]),
                      config=PiperConfig.from_dict(json.loads(Path(str(path) + ".json").read_text())))


@dataclass
class PCM:
    sample_rate: int
    audio_int16_bytes: bytes


def pcm(samples, rate):
    import numpy as np
    samples = np.nan_to_num(np.asarray(samples, dtype=np.float32).reshape(-1))
    active = np.flatnonzero(np.abs(samples) > .003)
    if not len(active):
        raise RuntimeError("Speech model returned no audible samples")
    # Preserve short edges while avoiding model-added leading/trailing silence.
    samples = samples[max(0, active[0] - int(rate * .005)):active[-1] + int(rate * .04) + 1]
    return PCM(rate, (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


class SileroVoice:
    def __init__(self, path, threads):
        import torch
        torch.set_num_threads(threads)
        self.torch = torch
        self.model = torch.package.PackageImporter(str(path)).load_pickle("tts_models", "model")
        self.model.to(torch.device("cpu"))
        self.speaker = os.getenv("HYPRCHAN_TTS_SPEAKER_RU", "kseniya")
        self.pitch = os.getenv("HYPRCHAN_TTS_RU_PITCH", "high")
        if self.pitch not in {"x-low", "low", "medium", "high", "x-high"}:
            raise ValueError("Russian pitch must be x-low, low, medium, high, or x-high")
        if self.speaker not in self.model.speakers:
            raise ValueError("Unknown Russian voice")
        self.label = f"Silero {self.speaker} ({self.pitch})"

    def synthesize(self, text):
        with self.torch.inference_mode():
            samples = self.model.apply_tts(
                ssml_text=f'<speak><prosody pitch="{self.pitch}">{escape(text)}</prosody></speak>',
                speaker=self.speaker, sample_rate=24000)
        yield pcm(samples.numpy(), 24000)


class KokoroVoice:
    def __init__(self, path, voices_path, threads):
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        self.model = Kokoro.from_session(ort.InferenceSession(str(path), sess_options=onnx_options(threads),
            providers=["CPUExecutionProvider"]), str(voices_path))
        self.speaker = os.getenv("HYPRCHAN_TTS_SPEAKER_EN", "af_bella")
        self.speed = max(.8, min(1.3, float(os.getenv("HYPRCHAN_TTS_EN_SPEED", "1.08"))))
        self.label = f"Kokoro {self.speaker}"

    def synthesize(self, text):
        samples, rate = self.model.create(text, voice=self.speaker, lang="en-us", speed=self.speed)
        yield pcm(samples, rate)


def load_voices(threads=4, backend=None):
    backend = backend or os.getenv("HYPRCHAN_TTS_BACKEND", "expressive")
    if backend == "piper":
        directory = Path(os.getenv("HYPRCHAN_TTS_VOICE_DIR", str(Path.home() / ".local/share/piper/voices")))
        voices = {}
        for language, name in [("en", "en_US-lessac-medium"), ("ru", "ru_RU-irina-medium")]:
            path = Path(os.getenv(f"HYPRCHAN_TTS_VOICE_{language.upper()}", str(directory / (name + ".onnx"))))
            voices[language] = load_voice(path, threads)
        return voices, {language: voice.config.espeak_voice for language, voice in voices.items()}, backend
    if backend != "expressive":
        raise ValueError("HYPRCHAN_TTS_BACKEND must be expressive or piper")
    directory = Path(os.getenv("HYPRCHAN_TTS_VOICE_DIR", str(Path.home() / ".local/share/hyprchan-codex/voices")))
    voices = {
        "ru": SileroVoice(Path(os.getenv("HYPRCHAN_TTS_VOICE_RU", str(directory / "silero-v5_5_ru.pt"))), threads),
        "en": KokoroVoice(Path(os.getenv("HYPRCHAN_TTS_VOICE_EN", str(directory / "kokoro-v1.0.onnx"))),
                          directory / "voices-v1.0.bin", threads),
    }
    return voices, {language: voice.label for language, voice in voices.items()}, backend
