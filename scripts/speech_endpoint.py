"""Streaming Silero v6 endpointing for the pinned faster-whisper preview runtime."""
from collections import deque
import math

import numpy as np
from faster_whisper.vad import get_vad_model


class VoiceSegmenter:
    sample_rate = 16000
    frame_size = 512

    def __init__(self, *, silence_ms=240):
        self.session = get_vad_model().session
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)
        self.pre_roll = deque(maxlen=8)
        self.end_frames = math.ceil(silence_ms / 32)
        self.endpoint_ms = self.end_frames * 32
        self.max_frames = 375  # 12 seconds
        self.active_frames = []
        self.is_speaking = False
        self.start_frames = 0
        self.silence_frames = 0
        self.voiced_frames = 0
        self.probability = 0.0

    def push(self, frame):
        frame = np.asarray(frame, dtype=np.float32).reshape(-1)
        if len(frame) != self.frame_size:
            raise ValueError("VoiceSegmenter expects 512 samples at 16 kHz")
        output, self.h, self.c = self.session.run(None, {
            "input": np.concatenate((self.context, frame.reshape(1, -1)), axis=1),
            "h": self.h, "c": self.c,
        })
        self.context = frame[-64:].reshape(1, -1).copy()
        self.probability = float(output.reshape(-1)[0])
        self.pre_roll.append(frame)
        if not self.is_speaking:
            self.start_frames = self.start_frames + 1 if self.probability >= 0.5 else 0
            if self.start_frames >= 2:
                self.is_speaking = True
                self.active_frames = list(self.pre_roll)
                self.voiced_frames = self.start_frames
                self.start_frames = self.silence_frames = 0
            return None
        self.active_frames.append(frame)
        if self.probability < 0.35:
            self.silence_frames += 1
        else:
            self.silence_frames = 0
            self.voiced_frames += 1
        if self.silence_frames < self.end_frames and len(self.active_frames) < self.max_frames:
            return None
        # Retain two trailing frames so a quiet final consonant isn't clipped.
        trim = max(0, self.silence_frames - 2)
        audio = self.active_frames[:-trim] if trim else self.active_frames
        valid = self.voiced_frames >= 3
        self.active_frames = []
        self.is_speaking = False
        self.start_frames = self.silence_frames = self.voiced_frames = 0
        return np.concatenate(audio).astype(np.float32) if valid and audio else None

    @staticmethod
    def dbfs(frame):
        rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
        return 20 * math.log10(max(rms, 1e-9))
