#!/usr/bin/env python3
"""Local speech worker. Audio stays in RAM; only transcripts leave this process."""
from __future__ import annotations

import argparse
import json
import itertools
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
from desktop_listen_in import capture_stream, listen_plan
from desktop_transcription import transcribe_playback, transcribe_microphone

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
        self.jobs = queue.PriorityQueue(maxsize=16)
        self.job_sequence = itertools.count()
        self.listen_generation = 0
        self.listen_process = None
        self.listening = None
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
                        self.jobs.put_nowait((0, next(self.job_sequence),
                            (utterance, generation, language, now, "microphone", segmenter.endpoint_ms)))
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
                _, _, job = self.jobs.get(timeout=0.5)
                audio, generation, language, endpoint, origin, silence_ms = job
            except queue.Empty:
                continue
            ambient = isinstance(origin, dict)
            if generation != (self.listen_generation if ambient else self.generation):
                continue
            if ambient and audio is None:
                with self.lock:
                    if generation == self.listen_generation:
                        self.listening = None
                        emit("listen_done", **origin)
                continue
            if not ambient:
                emit("transcribing", active=True)
            started = time.monotonic()
            rejected = None
            try:
                if ambient:
                    # The companion cannot know a new stream's language before
                    # hearing it. Never force its guess (or the mic selector).
                    name = self.model_name(None)
                    result = transcribe_playback(self.models[name], audio,
                        cancelled=lambda: generation != self.listen_generation or not self.running)
                    with self.lock:
                        if result is not None and generation == self.listen_generation:
                            emit("listen_chunk", **origin, **result, model=name,
                                 sttMs=round((time.monotonic() - started) * 1000, 1))
                else:
                    name = self.model_name(language)
                    recovery = self.model_name(None)
                    result = transcribe_microphone(self.models[name], audio, language,
                        retry_model=self.models[recovery],
                        cancelled=lambda: generation != self.generation or not self.running)
                    if result is not None and generation == self.generation:
                        if result['attempts'] > 1: name = recovery
                        if result['text']:
                            emit("transcript", **result,
                                 sttMs=round((time.monotonic() - started) * 1000, 1),
                                 endpointMs=round((time.monotonic() - endpoint) * 1000, 1),
                                 origin=origin, silenceMs=silence_ms, model=name)
                        elif result['recognitionStatus'] == 'unclear':
                            rejected = {key: result[key] for key in ('rejectionReason','retryReason','attempts','audioSeconds')}
                            rejected['model'] = name
            except Exception as exc:
                if ambient:
                    with self.lock:
                        if generation != self.listen_generation:
                            continue
                        self.stop_listening()
                emit("listen_error" if ambient else "error", message=str(exc), **(origin if ambient else {}))
            finally:
                if not ambient:
                    emit("transcribing", active=False)
                    if rejected and generation == self.generation:
                        emit("transcription_rejected", **rejected,
                             message="Speech was unclear after a retry; please say that again.")

    def stop_listening(self):
        with self.lock:
            self.listen_generation += 1
            child, self.listen_process = self.listen_process, None
            if child and child.poll() is None:
                child.terminate()
            job, self.listening = self.listening, None
            if job:
                emit("listen_done", jobId=job["jobId"], name=job["name"], cancelled=True)

    def listen_in(self, command):
        count, _ = listen_plan(command["seconds"])
        with self.lock:
            if self.listening:
                emit("listen_error", jobId=command["jobId"], message="Already listening to a playback stream")
                return
            self.listen_generation += 1
            generation = self.listen_generation
            self.listening = command
        metadata = {"jobId": command["jobId"], "name": command["name"], "total": count,
                    "serial": command["serial"], "seconds": command["seconds"]}
        def capture():
            index = 0
            def on_process(child):
                with self.lock:
                    if generation == self.listen_generation:
                        self.listen_process = child
                    elif child and child.poll() is None:
                        child.terminate()
            try:
                with self.lock:
                    if generation != self.listen_generation:
                        return
                    emit("listen_started", **metadata)
                for index, total, raw in capture_stream(command["serial"], command["seconds"],
                        lambda: generation != self.listen_generation or not self.running,
                        on_process):
                    self.jobs.put_nowait((1, next(self.job_sequence),
                        (np.frombuffer(raw, dtype="<f4"), generation, None,
                         time.monotonic(), {**metadata, "index": index}, 0)))
                with self.lock:
                    if generation == self.listen_generation:
                        if not index:
                            self.stop_listening()
                            emit("listen_error", **metadata, message="No audio arrived from that playback stream")
                            return
                        self.jobs.put_nowait((2, next(self.job_sequence),
                            (None, generation, None, time.monotonic(), {**metadata, "chunks": index}, 0)))
            except Exception as exc:
                with self.lock:
                    if generation == self.listen_generation:
                        self.stop_listening()
                        emit("listen_error", **metadata, message=str(exc))
        threading.Thread(target=capture, daemon=True).start()

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
                elif kind == "listen_in":
                    self.listen_in(command)
                elif kind == "stop_listening":
                    self.stop_listening()
                elif kind == "transcribe_file":
                    # Diagnostic input uses exactly the same transcriber and GUI reply path.
                    raw = subprocess.check_output([
                        "ffmpeg", "-nostdin", "-v", "error", "-i", command["path"],
                        "-t", "15", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1",
                    ])
                    self.jobs.put((0, next(self.job_sequence), (np.frombuffer(raw, dtype="<f4"), self.generation,
                                   command.get("language") or None, time.monotonic(), "test_audio", 0)))
        finally:
            self.running = False
            self.stop_listening()
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
