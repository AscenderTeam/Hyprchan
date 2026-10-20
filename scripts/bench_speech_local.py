#!/usr/bin/env python3
"""Measure warmed local STT on supplied audio; decoding is outside the timer."""
import argparse
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from faster_whisper import WhisperModel

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--models", default="tiny,base")
parser.add_argument("--trials", type=int, default=3)
parser.add_argument("--case", action="append", required=True, help="name:language:wav-path")
parser.add_argument("--out", required=True)
args = parser.parse_args()
cases = []
for value in args.case:
    name, language, path = value.split(":", 2)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"])
    cases.append((name, language, np.frombuffer(raw, dtype="<f4")))
rows = []
for model_name in args.models.split(","):
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1)
    list(model.transcribe(cases[0][2], language=cases[0][1], beam_size=1, vad_filter=True)[0])
    for trial in range(args.trials):
        for name, language, audio in cases:
            for mode in ("auto", "fixed"):
                start = time.perf_counter()
                segments, info = model.transcribe(audio, language=None if mode == "auto" else language,
                    beam_size=1, temperature=0, condition_on_previous_text=False, vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 200}, no_speech_threshold=0.6,
                    log_prob_threshold=-1, hallucination_silence_threshold=1)
                text = " ".join(segment.text.strip() for segment in segments).strip()
                row = {"model": model_name, "trial": trial, "case": name, "mode": mode,
                       "audioSeconds": len(audio) / 16000, "text": text, "language": info.language,
                       "sttMs": round((time.perf_counter() - start) * 1000, 2)}
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
Path(args.out).write_text(json.dumps({"cpuThreads": 4, "computeType": "int8", "trials": rows}, ensure_ascii=False, indent=2) + "\n")
