#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import os
import signal
from dataclasses import replace
from typing import Any

import numpy as np
import sounddevice as sd  # type: ignore

from hyprchan.core.hypraios.perception.speech_perception_source import (
    SpeechPerceptionConfig,
    SpeechPerceptionSource,
)
from hyprchan.settings import (
    SPEECH_END_SILENCE_SEC,
    SPEECH_FRAME_DURATION_MS,
    SPEECH_INPUT_DEVICE,
    SPEECH_LANGUAGE,
    SPEECH_MAX_SPEECH_SEC,
    SPEECH_MIN_CONTINUE_DBFS,
    SPEECH_MIN_SPEECH_SEC,
    SPEECH_MIN_START_DBFS,
    SPEECH_PRE_ROLL_SEC,
)


class _PassthroughTranscriber:
    def transcribe(self, audio: np.ndarray) -> str:
        _ = audio
        return "[transcription disabled: speech boundary detected]"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Debug live speech perception (VAD + Whisper)"
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available input devices and exit.",
    )
    parser.add_argument(
        "--device",
        default=SPEECH_INPUT_DEVICE,
        help="Input device index or name substring. Defaults to SPEECH_INPUT_DEVICE/default mic.",
    )
    parser.add_argument(
        "--language",
        default=SPEECH_LANGUAGE,
        help="Whisper language hint (default: en).",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("SPEECH_MODEL_NAME", "Systran/faster-whisper-large-v3"),
        help="Whisper model id (default: Systran/faster-whisper-large-v3).",
    )
    parser.add_argument(
        "--no-transcribe",
        action="store_true",
        help="Disable Whisper and only test speech boundary detection.",
    )
    return parser.parse_args()


def _list_devices() -> None:
    devices = list(sd.query_devices())
    default_pair = sd.default.device
    default_input = None
    if isinstance(default_pair, (list, tuple)) and len(default_pair) >= 1:
        default_input = default_pair[0]

    print("Input devices:")
    for idx, info in enumerate(devices):
        try:
            max_input = int(info.get("max_input_channels", 0))
        except (TypeError, ValueError):
            max_input = 0
        if max_input <= 0:
            continue
        marker = "*" if idx == default_input else " "
        name = str(info.get("name", f"device-{idx}"))
        sr = info.get("default_samplerate", "?")
        print(f" {marker} [{idx:2d}] {name} (max_in={max_input}, default_sr={sr})")


async def _run_debug(args: argparse.Namespace) -> None:
    base_config = SpeechPerceptionConfig(
        frame_duration_ms=SPEECH_FRAME_DURATION_MS,
        min_speech_sec=SPEECH_MIN_SPEECH_SEC,
        end_silence_sec=SPEECH_END_SILENCE_SEC,
        max_speech_sec=SPEECH_MAX_SPEECH_SEC,
        pre_roll_sec=SPEECH_PRE_ROLL_SEC,
        min_start_dbfs=SPEECH_MIN_START_DBFS,
        min_continue_dbfs=SPEECH_MIN_CONTINUE_DBFS,
        input_device=SPEECH_INPUT_DEVICE,
        language=SPEECH_LANGUAGE,
    )
    config = replace(
        base_config,
        input_device=str(args.device or ""),
        language=str(args.language or "en"),
        model_name=str(args.model or "Systran/faster-whisper-large-v3"),
    )

    detected_events: list[dict[str, Any]] = []

    async def _on_event(event: dict[str, Any]) -> None:
        detected_events.append(event)
        print("\n\n--- speech event ---")
        print(f"text: {event.get('description', '')}")
        print(
            f"duration: {event.get('speech_duration_sec', '?')}s | device: {event.get('input_device_name', '?')}"
        )
        print("--------------------")

    source = SpeechPerceptionSource(
        _on_event,
        config=config,
        transcriber=_PassthroughTranscriber() if args.no_transcribe else None,
    )

    stop_event = asyncio.Event()

    def _request_stop(*_unused: Any) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for signame in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signame, _request_stop)
        except NotImplementedError:
            pass

    print("Starting speech debug... (Ctrl+C to stop)")
    print("If no events appear, speak louder or lower SPEECH_MIN_START_DBFS.")
    print()

    await source.start()

    try:
        while not stop_event.is_set():
            status = source.status()
            obs = status.get("last_observation") or {}
            dbfs = float(obs.get("dbfs", -120.0) or -120.0)
            noise = float(obs.get("noise_floor_dbfs", -55.0) or -55.0)
            start_thr = max(
                config.min_start_dbfs,
                noise + config.noise_gate_margin_start_db,
            )
            cont_thr = max(
                config.min_continue_dbfs,
                noise + config.noise_gate_margin_continue_db,
            )
            speaking = bool(obs.get("speaking", False))
            dropped = int(status.get("dropped_frames", 0) or 0)
            device = status.get("input_device_name") or "default-input"
            print(
                "\r"
                f"device={device} | dbfs={dbfs:6.1f} | noise={noise:6.1f} | "
                f"start>={start_thr:6.1f} | continue>={cont_thr:6.1f} | "
                f"speaking={str(speaking):5s} | dropped={dropped:4d} | events={len(detected_events):3d}",
                end="",
                flush=True,
            )
            await asyncio.sleep(0.2)
    finally:
        await source.stop()
        print("\nStopped speech debug.")


def main() -> None:
    args = _parse_args()
    if args.list_devices:
        _list_devices()
        return

    asyncio.run(_run_debug(args))


if __name__ == "__main__":
    main()
