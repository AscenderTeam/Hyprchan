"""Playback recognition policy; media language comes from audio, never chat."""
import math
import re


def transcription_issue(segments):
    for segment in segments:
        # Whisper's compression/log-probability thresholds trigger decoding
        # fallback, but its final candidate can still fail those thresholds.
        if (re.search(r"([^\W\d_])\1{7,}", segment.text, re.IGNORECASE)
                or segment.compression_ratio > 2.4):
            return "repetition"
        if segment.avg_logprob < -1:
            return "low_confidence"
    return None


def transcribe_playback(model, audio, cancelled=lambda: False):
    """One fast decode, at most one wider-beam retry, then an honest empty result.

    The caller supplies the warmed automatic-language model. Language is always
    detected from this chunk, including when an old client sends a language hint.
    No previous text is used: an earlier mistake must not poison later chunks.
    """
    retry_reason = None
    for attempt, beam_size in enumerate((1, 3), start=1):
        if cancelled():
            return None
        segments, info = model.transcribe(
            audio, language=None, beam_size=beam_size, temperature=0,
            condition_on_previous_text=False, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 200},
            no_speech_threshold=0.6, log_prob_threshold=-1,
            # Bound runaway output without removing repetitions from real text.
            max_new_tokens=min(256, max(64, math.ceil(len(audio) / 16000 * 20) + 16)),
        )
        segments = list(segments)
        issue = transcription_issue(segments)
        if issue and attempt == 1:
            retry_reason = issue
            continue
        text = "" if issue else " ".join(part.text.strip() for part in segments).strip()
        return {
            "text": text,
            "language": info.language if segments else None,
            "languageProbability": round(info.language_probability, 3) if segments else None,
            "languageMode": "auto",
            "recognitionStatus": "unclear" if issue else "ok" if text else "no_speech",
            "rejectionReason": issue,
            "retryReason": retry_reason,
            "attempts": attempt,
            "audioSeconds": round(len(audio) / 16000, 3),
            "speechSeconds": round(info.duration_after_vad, 3),
        }
