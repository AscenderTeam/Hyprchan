#!/usr/bin/env python3
"""Warm local voices with cancellable, phrase-streamed PipeWire playback."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

from desktop_speech_output import speech_language
from desktop_local_voices import load_voices

OUTPUT_LOCK = threading.Lock()


def emit(kind, **values):
    with OUTPUT_LOCK:
        print(json.dumps({"type": kind, **values}, ensure_ascii=False), flush=True)


@dataclass
class SpeechJob:
    identity: int
    started: float = field(default_factory=time.monotonic)
    cancelled: threading.Event = field(default_factory=threading.Event)
    language: str | None = None
    segments: int = 0
    first_pcm_ms: float | None = None
    first_write_ms: float | None = None


class SpeechOutput:
    def __init__(self):
        self.lock = threading.RLock()
        self.running = True
        self.current = None
        self.player = None
        self.synthesis = queue.Queue(maxsize=32)
        self.audio = queue.Queue(maxsize=16)
        self.target = os.getenv("HYPRCHAN_TTS_SINK") or subprocess.check_output(
            ["pactl", "get-default-sink"], text=True, timeout=3).strip()
        self.volume = max(0, min(1, float(os.getenv("HYPRCHAN_TTS_VOLUME", "0.65"))))
        threads = max(1, min(8, int(os.getenv("HYPRCHAN_TTS_THREADS", "4"))))
        self.voices, labels, backend = load_voices(threads)
        for language, voice in self.voices.items():
            list(voice.synthesize("Привет!" if language == "ru" else "Hi!"))
        emit("ready", voices=labels, engine=backend, sink=self.target, threads=threads)
        self.threads = [threading.Thread(target=target, daemon=True) for target in [self.synthesize, self.play]]
        for thread in self.threads:
            thread.start()

    def cancel(self):
        with self.lock:
            job, self.current = self.current, None
            if job:
                job.cancelled.set()
            child, self.player = self.player, None
            if child and child.poll() is None:
                child.terminate()
            if job:
                emit("cancelled", id=job.identity)

    def enqueue(self, target, value, job):
        while self.running and not job.cancelled.is_set():
            try:
                target.put(value, timeout=.05)
                return True
            except queue.Full:
                pass
        return False

    def synthesize(self):
        while self.running:
            try:
                job, phrases = self.synthesis.get(timeout=.2)
            except queue.Empty:
                continue
            if job.cancelled.is_set():
                continue
            if phrases is None:
                self.enqueue(self.audio, (job, None), job)
                continue
            started = time.monotonic()
            try:
                for text in phrases:
                    if job.cancelled.is_set():
                        break
                    if job.language is None:
                        job.language = speech_language(text)
                    for chunk in self.voices[job.language].synthesize(text):
                        if job.cancelled.is_set():
                            break
                        now = time.monotonic()
                        if job.first_pcm_ms is None:
                            job.first_pcm_ms = (now - job.started) * 1000
                            emit("generated", id=job.identity, language=job.language,
                                 firstPcmMs=round(job.first_pcm_ms, 1), synthMs=round((now - started) * 1000, 1))
                        if not self.enqueue(self.audio, (job, chunk), job):
                            break
                    if not job.cancelled.is_set():
                        job.segments += 1
            except Exception as exc:
                self.fail(job, str(exc))

    def fail(self, job, message):
        with self.lock:
            if self.current is job and not job.cancelled.is_set():
                self.cancel()
                emit("error", id=job.identity, message=message)

    @staticmethod
    def finish_player(child):
        try:
            child.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            return child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            raise RuntimeError("Speech playback did not finish")

    def play(self):
        child = None
        playing = None
        while self.running:
            try:
                job, chunk = self.audio.get(timeout=.2)
            except queue.Empty:
                if child and playing.cancelled.is_set():
                    self.finish_player(child)
                    child = playing = None
                continue
            if job.cancelled.is_set():
                if playing is job and child:
                    self.finish_player(child)
                    child = playing = None
                continue
            try:
                if chunk is None:
                    code = self.finish_player(child) if child and playing is job else 0
                    with self.lock:
                        if self.current is job and not job.cancelled.is_set():
                            self.player = None
                            self.current = None
                            if code:
                                emit("error", id=job.identity, message=f"Speech playback exited ({code})")
                            else:
                                emit("done", id=job.identity, language=job.language,
                                     firstPcmMs=job.first_pcm_ms, firstWriteMs=job.first_write_ms,
                                     segments=job.segments,
                                     elapsedMs=round((time.monotonic() - job.started) * 1000, 1))
                    child = playing = None
                    continue
                if playing is not job:
                    if child:
                        self.finish_player(child)
                    with self.lock:
                        if job.cancelled.is_set():
                            child = playing = None
                            continue
                        props = {"application.name": "Hyprchan voice", "node.name": "hyprchan-voice",
                                 "media.name": "Hyprchan speech", "node.dont-reconnect": True}
                        child = subprocess.Popen(["pw-play", "--raw", "--format", "s16", "--rate", str(chunk.sample_rate),
                            "--channels", "1", "--latency", "20ms", "--target", self.target,
                            "--volume", str(self.volume), "-P", json.dumps(props), "-"],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, bufsize=0)
                        self.player = child
                        playing = job
                # A cancelled player's closed pipe unblocks any backpressure here.
                raw = chunk.audio_int16_bytes
                offset = 0
                while offset < len(raw) and not job.cancelled.is_set():
                    end = min(offset + 2048, len(raw))
                    written = child.stdin.write(raw[offset:end])
                    if not written:
                        raise RuntimeError("Speech playback pipe closed")
                    offset += written
                    if job.first_write_ms is None:
                        job.first_write_ms = (time.monotonic() - job.started) * 1000
                        emit("playing", id=job.identity, firstWriteMs=round(job.first_write_ms, 1),
                             firstPcmMs=round(job.first_pcm_ms, 1), language=job.language)
            except Exception as exc:
                self.fail(job, str(exc))
                if child:
                    if child.poll() is None:
                        child.terminate()
                    self.finish_player(child)
                child = playing = None
        if child:
            if child.poll() is None:
                child.terminate()
            self.finish_player(child)

    def run(self):
        try:
            for line in sys.stdin:
                command = json.loads(line)
                kind = command.get("type")
                if kind == "quit":
                    break
                if kind == "stop":
                    self.cancel()
                elif kind == "begin":
                    self.cancel()
                    with self.lock:
                        self.current = SpeechJob(command["id"])
                elif kind in {"text", "end"}:
                    with self.lock:
                        job = self.current
                        if not job or job.identity != command["id"] or job.cancelled.is_set():
                            continue
                        phrases = command.get("phrases", [str(command.get("text", ""))[:500]]) if kind == "text" else None
                        if phrases is not None and (not isinstance(phrases, list) or len(phrases) > 256 or
                                any(not isinstance(text, str) or len(text) > 500 for text in phrases) or
                                sum(map(len, phrases)) > 8000):
                            self.fail(job, "Invalid speech phrase batch")
                            continue
                        if phrases == [] or phrases == [""]:
                            continue
                        try:
                            self.synthesis.put_nowait((job, phrases))
                        except queue.Full:
                            self.fail(job, "Speech queue full; playback cancelled")
        finally:
            self.cancel()
            self.running = False
            for thread in self.threads:
                thread.join(timeout=2)


if __name__ == "__main__":
    worker = None
    def stop(*_):
        if worker:
            worker.cancel()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        worker = SpeechOutput()
        worker.run()
    except Exception as exc:
        emit("error", fatal=True, message=str(exc))
