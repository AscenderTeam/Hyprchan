"""Regression checks for wrong-language hints and failed Whisper decodes."""
from types import SimpleNamespace
import unittest

from desktop_transcription import transcribe_playback


def response(text, language="en", logprob=-0.4, compression=1.2):
    segments = [SimpleNamespace(text=text, avg_logprob=logprob, compression_ratio=compression)] if text else []
    return segments, SimpleNamespace(language=language, language_probability=0.9, duration_after_vad=2)


class Decoder:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def transcribe(self, audio, **options):
        self.calls.append(options)
        segments, info = next(self.responses)
        return iter(segments), info


class PlaybackTranscriptionTests(unittest.TestCase):
    def test_audio_selects_each_language_without_a_chat_hint(self):
        for text, language in [("Hello, how are you?", "en"), ("Привет, как дела?", "ru")]:
            decoder = Decoder(response(text, language))
            result = transcribe_playback(decoder, range(32000))
            self.assertEqual(result["text"], text)
            self.assertEqual(result["language"], language)
            self.assertEqual(result["attempts"], 1)
            self.assertIsNone(decoder.calls[0]["language"])
            self.assertFalse(decoder.calls[0]["condition_on_previous_text"])

    def test_repetition_is_retried_then_replaced_by_recovered_speech(self):
        decoder = Decoder(response("А" + "э" * 200, "ru"), response("An English voice message."))
        result = transcribe_playback(decoder, range(32000))
        self.assertEqual(result["text"], "An English voice message.")
        self.assertEqual(result["language"], "en")
        self.assertEqual(result["retryReason"], "repetition")
        self.assertEqual([call["beam_size"] for call in decoder.calls], [1, 3])

    def test_repeated_gibberish_is_never_returned_as_a_transcript(self):
        decoder = Decoder(response("А" + "э" * 200, "ru"), response("А" + "э" * 200, "ru"))
        result = transcribe_playback(decoder, range(32000))
        self.assertEqual(result["text"], "")
        self.assertEqual(result["recognitionStatus"], "unclear")
        self.assertEqual(result["rejectionReason"], "repetition")
        self.assertEqual(len(decoder.calls), 2)

    def test_repeated_phrases_and_low_confidence_are_not_treated_as_success(self):
        for bad in [response("thank you " * 20, compression=4), response("Imagined words", logprob=-1.6)]:
            decoder = Decoder(bad, bad)
            result = transcribe_playback(decoder, range(32000))
            self.assertEqual(result["text"], "")
            self.assertEqual(result["recognitionStatus"], "unclear")

    def test_real_short_repetitions_are_preserved(self):
        text = "No, no, no! Mmm, okay."
        self.assertEqual(transcribe_playback(Decoder(response(text)), range(32000))["text"], text)

    def test_silence_does_not_retry_or_claim_a_detected_language(self):
        decoder = Decoder(response(""))
        result = transcribe_playback(decoder, range(32000))
        self.assertEqual(result["recognitionStatus"], "no_speech")
        self.assertIsNone(result["language"])
        self.assertIsNone(result["languageProbability"])
        self.assertEqual(len(decoder.calls), 1)

    def test_cancellation_prevents_an_expensive_retry(self):
        decoder = Decoder(response("А" + "э" * 200, "ru"))
        result = transcribe_playback(decoder, range(32000), cancelled=lambda: bool(decoder.calls))
        self.assertIsNone(result)
        self.assertEqual(len(decoder.calls), 1)


if __name__ == "__main__":
    unittest.main()
