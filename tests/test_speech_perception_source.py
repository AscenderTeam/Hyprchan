from unittest.mock import AsyncMock

import numpy as np
import pytest

from core.hypraios.perception.speech_perception_source import (
    SpeechPerceptionConfig,
    SpeechPerceptionSource,
    SpeechSegmenter,
    SpeechTranscription,
)


def _frame(config: SpeechPerceptionConfig, amplitude: float) -> np.ndarray:
    return np.full((config.frame_size,), amplitude, dtype=np.float32)


def test_speech_segmenter_emits_utterance_after_silence_boundary() -> None:
    config = SpeechPerceptionConfig()
    segmenter = SpeechSegmenter(config)

    emitted: np.ndarray | None = None

    for _ in range(15):
        segmenter.push(_frame(config, 0.0007))

    for _ in range(22):
        emitted = segmenter.push(_frame(config, 0.08))
        if emitted is not None:
            break

    if emitted is None:
        for _ in range(45):
            emitted = segmenter.push(_frame(config, 0.0007))
            if emitted is not None:
                break

    assert emitted is not None
    assert float(emitted.shape[0]) / config.sample_rate >= config.min_speech_sec


def test_speech_segmenter_ignores_too_short_burst() -> None:
    config = SpeechPerceptionConfig(min_speech_sec=0.4)
    segmenter = SpeechSegmenter(config)

    emitted: np.ndarray | None = None
    for _ in range(8):
        segmenter.push(_frame(config, 0.0006))
    for _ in range(4):
        emitted = segmenter.push(_frame(config, 0.08))
    for _ in range(40):
        emitted = segmenter.push(_frame(config, 0.0006))
        if emitted is not None:
            break

    assert emitted is None


@pytest.mark.asyncio
async def test_speech_source_emits_transcript_event() -> None:
    class FakeTranscriber:
        def transcribe(self, audio: np.ndarray) -> str:
            assert audio.size > 0
            return "hello from speech"

    callback = AsyncMock()
    config = SpeechPerceptionConfig(
        frame_duration_ms=30,
        min_speech_sec=0.06,
        end_silence_sec=0.06,
        pre_roll_sec=0.03,
        min_start_dbfs=-45.0,
        min_continue_dbfs=-50.0,
    )
    source = SpeechPerceptionSource(
        callback, config=config, transcriber=FakeTranscriber()
    )

    event = None
    for _ in range(12):
        event = await source._consume_frame(_frame(config, 0.06), emit=True)
        if event is not None:
            break
    if event is None:
        for _ in range(12):
            event = await source._consume_frame(_frame(config, 0.0007), emit=True)
            if event is not None:
                break

    assert event is not None
    assert event["origin"] == "communication_controller"
    assert event["type"] == "communication_message"
    assert event["description"] == "hello from speech"
    assert callback.await_count == 1


@pytest.mark.asyncio
async def test_speech_source_emits_detected_language_metadata() -> None:
    class FakeTranscriber:
        def transcribe(self, audio: np.ndarray) -> SpeechTranscription:
            assert audio.size > 0
            return SpeechTranscription(
                text="hola desde voz",
                language="es",
                language_confidence=0.93,
            )

    callback = AsyncMock()
    config = SpeechPerceptionConfig(
        frame_duration_ms=30,
        min_speech_sec=0.06,
        end_silence_sec=0.06,
        pre_roll_sec=0.03,
        min_start_dbfs=-45.0,
        min_continue_dbfs=-50.0,
    )
    source = SpeechPerceptionSource(
        callback, config=config, transcriber=FakeTranscriber()
    )

    event = None
    for _ in range(12):
        event = await source._consume_frame(_frame(config, 0.06), emit=True)
        if event is not None:
            break
    if event is None:
        for _ in range(12):
            event = await source._consume_frame(_frame(config, 0.0007), emit=True)
            if event is not None:
                break

    assert event is not None
    assert event["speech_language"] == "es"
    assert event["speech_language_confidence"] == 0.93


@pytest.mark.asyncio
async def test_speech_source_reports_vad_and_transcription_state() -> None:
    class FakeTranscriber:
        def transcribe(self, audio: np.ndarray) -> str:
            assert audio.size > 0
            return "glow test"

    callback = AsyncMock()
    speaking_state = AsyncMock()
    transcription_state = AsyncMock()
    config = SpeechPerceptionConfig(
        frame_duration_ms=30,
        min_speech_sec=0.06,
        end_silence_sec=0.06,
        pre_roll_sec=0.03,
        min_start_dbfs=-45.0,
        min_continue_dbfs=-50.0,
    )
    source = SpeechPerceptionSource(
        callback,
        config=config,
        transcriber=FakeTranscriber(),
        speaking_state_callback=speaking_state,
        transcription_state_callback=transcription_state,
    )

    event = None
    for _ in range(12):
        event = await source._consume_frame(_frame(config, 0.06), emit=True)
        if event is not None:
            break
    if event is None:
        for _ in range(12):
            event = await source._consume_frame(_frame(config, 0.0007), emit=True)
            if event is not None:
                break

    assert event is not None
    speaking_sequence = [call.args[0] for call in speaking_state.await_args_list]
    assert speaking_sequence[:2] == [True, False]

    transcription_sequence = [
        call.args[0] for call in transcription_state.await_args_list
    ]
    assert transcription_sequence[:2] == [True, False]
    assert float(transcription_state.await_args_list[0].args[1]) > 0


def test_resample_audio_if_needed_changes_length_for_different_sample_rates() -> None:
    audio = np.linspace(-0.2, 0.2, num=4800, dtype=np.float32)
    resampled = SpeechPerceptionSource._resample_audio_if_needed(
        audio,
        source_sample_rate=48000,
        target_sample_rate=16000,
    )

    assert resampled.dtype == np.float32
    assert 1500 <= resampled.shape[0] <= 1700
