#!/usr/bin/env python3
"""Local speech worker. Audio stays in RAM; only transcripts leave this process."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

import numpy as np
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from speech_endpoint import VoiceSegmenter  # noqa: E402

OUTPUT_LOCK = threading.Lock()


def emit(kind: str, **values) -> None:
    with OUTPUT_LOCK:
        print(json.dumps({"type": kind, **values}, ensure_ascii=False), flush=True)


class SpeechWorker:
    def __init__(self, model_name: str):
        self.capture = None
        self.running = True
        self.generation = 0
        self.lock = threading.RLock()
        self.jobs = queue.Queue(maxsize=2)
        self.requested_model = model_name
        self.models = {}
        emit("loading", model=model_name)
        # Keep both cached: changing the language selector needs no model restart.
        for name in (("tiny", "base") if model_name == "auto" else (model_name,)):
            model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1)
            self.models[name] = model
            segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="en", beam_size=1)
            list(segments)
        VoiceSegmenter().push(np.zeros(512, dtype=np.float32))
        emit("ready", model=model_name)
        threading.Thread(target=self.transcribe_loop, daemon=True).start()

    def model_name(self, language: str | None) -> str:
        if self.requested_model != "auto":
            return self.requested_model
        return "tiny" if language in {"en", "ru"} else "base"

    def stop_capture(self) -> None:
        with self.lock:
            self.generation += 1
            child, self.capture = self.capture, None
            if child is not None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            emit("mic", active=False)

    def start_capture(self, source: str, language: str | None) -> None:
        self.stop_capture()
        with self.lock:
            generation = self.generation
            child = subprocess.Popen([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "pulse", "-name", "Hyprchan", "-stream_name", "Hyprchan microphone",
                "-fragment_size", "1024", "-sample_rate", "16000", "-channels", "1",
                "-i", source, "-ac", "1", "-ar", "16000", "-f", "f32le",
                "-flush_packets", "1", "pipe:1",
            ], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.capture = child
            threading.Thread(target=self.capture_loop,
                             args=(child, generation, language), daemon=True).start()

    def capture_loop(self, child, generation: int, language: str | None) -> None:
        segmenter = VoiceSegmenter(silence_ms=int(os.getenv("HYPRCHAN_END_SILENCE_MS", "240")))
        last_meter = 0.0
        last_speaking = False
        frames = 0
        try:
            while self.running and generation == self.generation:
                raw = child.stdout.read(segmenter.frame_size * 4)
                if len(raw) != segmenter.frame_size * 4:
                    break
                if generation != self.generation:
                    break
                frame = np.frombuffer(raw, dtype="<f4")
                frames += 1
                if frames == 1:
                    emit("mic", active=True, model=self.model_name(language))
                utterance = segmenter.push(frame)
                now = time.monotonic()
                if now - last_meter > 0.1:
                    emit("level", dbfs=round(segmenter.dbfs(frame), 1), frames=frames,
                         speaking=segmenter.is_speaking, voiceProbability=round(segmenter.probability, 3))
                    last_meter = now
                if segmenter.is_speaking != last_speaking:
                    last_speaking = segmenter.is_speaking
                    emit("speaking", active=last_speaking)
                if utterance is not None:
                    try:
                        self.jobs.put_nowait((utterance, generation, language, now, "microphone", segmenter.endpoint_ms))
                    except queue.Full:
                        emit("notice", message="Speech queue full; please pause between messages.")
        except Exception as exc:
            if generation == self.generation:
                emit("error", message=str(exc))
        finally:
            if generation == self.generation:
                error = child.stderr.read(2000).decode(errors="replace") if child.poll() is not None else ""
                emit("mic", active=False)
                emit("error", message=error or "Microphone disconnected. Select a microphone and enable it again.")

    def transcribe_loop(self) -> None:
        while self.running:
            try:
                audio, generation, language, endpoint, origin, silence_ms = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            if generation != self.generation:
                continue
            emit("transcribing", active=True)
            started = time.monotonic()
            try:
                name = self.model_name(language)
                segments, info = self.models[name].transcribe(
                    audio, language=language, beam_size=1, temperature=0,
                    condition_on_previous_text=False, vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 200},
                    no_speech_threshold=0.6, log_prob_threshold=-1,
                    hallucination_silence_threshold=1,
                )
                text = " ".join(part.text.strip() for part in segments).strip()
                if generation == self.generation and text:
                    emit("transcript", text=text, language=info.language,
                         sttMs=round((time.monotonic() - started) * 1000, 1),
                         endpointMs=round((time.monotonic() - endpoint) * 1000, 1),
                         origin=origin, silenceMs=silence_ms, model=name)
            except Exception as exc:
                emit("error", message=str(exc))
            finally:
                emit("transcribing", active=False)

    def run(self) -> None:
        try:
            for line in sys.stdin:
                command = json.loads(line)
                kind = command.get("type")
                if kind == "quit":
                    break
                if kind == "listen":
                    self.start_capture(command["source"], command.get("language") or None)
                elif kind == "mute":
                    self.stop_capture()
                elif kind == "transcribe_file":
                    # Diagnostic input uses exactly the same transcriber and GUI reply path.
                    raw = subprocess.check_output([
                        "ffmpeg", "-nostdin", "-v", "error", "-i", command["path"],
                        "-t", "15", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1",
                    ])
                    self.jobs.put((np.frombuffer(raw, dtype="<f4"), self.generation,
                                   command.get("language") or None, time.monotonic(), "test_audio", 0))
        finally:
            self.running = False
            self.stop_capture()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("HYPRCHAN_STT_MODEL", "auto"))
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        SpeechWorker(args.model).run()
    except Exception as exc:
        emit("error", fatal=True, message=str(exc))
        raise


if __name__ == "__main__":
    main()
