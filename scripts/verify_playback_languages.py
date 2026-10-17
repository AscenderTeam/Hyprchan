#!/usr/bin/env python3
"""Check playback language and latency on supplied public/synthetic fixtures."""
import argparse
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from faster_whisper import WhisperModel

from desktop_transcription import transcribe_playback


def load(path):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path),
        "-t", "15", "-ar", "16000", "-ac", "1", "-f", "f32le", "pipe:1"])
    return np.frombuffer(raw, dtype="<f4")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english", type=Path, required=True, help="Synthetic English greeting")
    parser.add_argument("--russian", type=Path, required=True, help="Synthetic Russian greeting")
    parser.add_argument("--jfk", type=Path, required=True, help="Public faster-whisper JFK fixture")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    en, ru, jfk = (load(path) for path in (args.english, args.russian, args.jfk))
    model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=4,
                         num_workers=1, local_files_only=True)
    cases = [("english", "en", en[:64000]), ("russian", "ru", ru[:64000]),
             ("english_quiet", "en", en[:64000] * .15), ("russian_quiet", "ru", ru[:64000] * .15)]
    cases += [(f"jfk_chunk_{i+1}", "en", jfk[i*38400:(i+1)*38400]) for i in range(5)]
    cases += [("silence", None, np.zeros(64000, dtype=np.float32)),
              ("noise", None, np.random.default_rng(7).normal(0, .01, 64000).astype(np.float32))]
    transcribe_playback(model, en[:64000])
    rows = []
    for trial in range(2):
        for name, expected, audio in cases:
            started = time.monotonic()
            result = transcribe_playback(model, audio)
            row = {"trial": trial, "case": name, "expectedLanguage": expected, **result,
                   "sttMs": round((time.monotonic() - started) * 1000, 1)}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    passed = all(row["language"] == row["expectedLanguage"] and
                 bool(row["text"]) == (row["expectedLanguage"] is not None) for row in rows)
    args.out.write_text(json.dumps({"publicAndSyntheticOnly": True, "model": "base", "cpuThreads": 4,
        "computeType": "int8", "passed": passed, "trials": rows,
        "limitation": "Fixtures do not reproduce the private Telegram recording or prove accuracy for arbitrary speech."},
        ensure_ascii=False, indent=2) + "\n")
    if not passed:
        raise SystemExit("Playback language or silence regression; see output")


if __name__ == "__main__":
    main()
