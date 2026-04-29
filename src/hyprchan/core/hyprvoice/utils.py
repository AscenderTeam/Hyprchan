from io import BytesIO
from pathlib import Path

_VOICE_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "assets" / "voice_samples"
_MAIN_SAMPLE = _VOICE_SAMPLES_DIR / "main_sample.mp3"


def get_sample_voice() -> BytesIO:
    return BytesIO(_MAIN_SAMPLE.read_bytes())


def get_sample_voice_path() -> str:
    return str(_MAIN_SAMPLE)


def get_reference_text() -> str | None:
    return None
