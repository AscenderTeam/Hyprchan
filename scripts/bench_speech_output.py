#!/usr/bin/env python3
"""Measure warmed local TTS generation, excluding playback, with synthetic text."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
from desktop_local_voices import load_voices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--backend", choices=["expressive", "piper"], default="expressive")
    parser.add_argument("--voice-dir", type=Path)
    parser.add_argument("--threads", default="4")
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    threads_to_test = [int(value) for value in args.threads.split(",")]
    if not threads_to_test or any(value < 1 or value > 8 for value in threads_to_test) or args.rounds < 1:
        parser.error("Use 1–8 threads and at least one round")
    if args.voice_dir:
        os.environ["HYPRCHAN_TTS_VOICE_DIR"] = str(args.voice_dir)
    default_dir = ".local/share/hyprchan-codex/voices" if args.backend == "expressive" else ".local/share/piper/voices"
    directory = Path(os.getenv("HYPRCHAN_TTS_VOICE_DIR", str(Path.home() / default_dir)))
    names = {"ru": "silero-v5_5_ru.pt", "en": "kokoro-v1.0.onnx"} if args.backend == "expressive" else {
        "ru": "ru_RU-irina-medium.onnx", "en": "en_US-lessac-medium.onnx"}
    paths = [Path(os.getenv(f"HYPRCHAN_TTS_VOICE_{language.upper()}", str(directory / name)))
             for language, name in names.items()]
    paths += [directory / "voices-v1.0.bin"] if args.backend == "expressive" else [Path(str(path) + ".json") for path in paths]
    assets = []
    for path in paths:
        with path.open("rb") as source:
            assets.append({"name": path.name, "sha256": hashlib.file_digest(source, "sha256").hexdigest()})
    versions = {}
    for package in ["torch", "kokoro-onnx", "onnxruntime", "piper-tts"]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    rows = []
    for threads in threads_to_test:
        start = time.perf_counter()
        voices, labels, backend = load_voices(threads, args.backend)
        load_ms = (time.perf_counter() - start) * 1000
        for language, texts in [
            ("ru", ["Привет!", "Привет, я уже тут!", "Ура, все тесты прошли. Маленькая победа!"]),
            ("en", ["Hi!", "Hi, I am right here!", "The tests passed. Tiny victory!"]),
        ]:
            voice = voices[language]
            list(voice.synthesize(texts[0]))
            for repeat in range(args.rounds):
                for text in texts:
                    start = time.perf_counter()
                    first = None
                    duration = 0
                    for chunk in voice.synthesize(text):
                        if first is None:
                            first = (time.perf_counter() - start) * 1000
                        duration += len(chunk.audio_int16_bytes) / 2 / chunk.sample_rate
                    rows.append({"language": language, "voice": labels[language], "threads": threads, "round": repeat,
                        "text": text, "loadBothMs": round(load_ms, 1), "firstPcmMs": round(first, 1),
                        "allPcmMs": round((time.perf_counter() - start) * 1000, 1),
                        "audioSec": round(duration, 3)})
        del voice, voices
    result = {"syntheticTextOnly": True, "backend": backend, "versions": versions,
              "voices": labels, "assets": assets, "rows": rows}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for threads in threads_to_test:
        for language in ["ru", "en"]:
            values = [row["firstPcmMs"] for row in rows if row["threads"] == threads and row["language"] == language]
            print(f"{language}, {threads} threads: first PCM {min(values):.1f}–{max(values):.1f} ms, {len(values)} trials")


if __name__ == "__main__":
    main()
