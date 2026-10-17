"""Regression checks for wrong-language hints and failed Whisper decodes."""
from types import SimpleNamespace
import unittest

from desktop_transcription import transcribe_playback, transcribe_microphone


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


class MicrophoneTranscriptionTests(unittest.TestCase):
    def test_clear_speech_keeps_the_fast_path_and_manual_language(self):
        fast = Decoder(response('Привет!', 'ru'))
        recovery = Decoder()
        result = transcribe_microphone(fast, range(16000), 'ru', recovery)
        self.assertEqual(result['text'], 'Привет!')
        self.assertEqual(result['attempts'], 1)
        self.assertEqual(result['languageMode'], 'manual')
        self.assertEqual(fast.calls[0]['language'], 'ru')
        self.assertEqual(fast.calls[0]['beam_size'], 1)
        self.assertFalse(recovery.calls)
        self.assertLessEqual(fast.calls[0]['max_new_tokens'], 64)

    def test_loop_retries_the_audio_with_the_warmed_recovery_model(self):
        fast = Decoder(response('За окном снова идёт дождь. '*20, 'ru'))
        recovery = Decoder(response('За окном идёт дождь.', 'ru'))
        result = transcribe_microphone(fast, range(32000), 'ru', recovery)
        self.assertEqual(result['text'], 'За окном идёт дождь.')
        self.assertEqual(result['retryReason'], 'repetition')
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(recovery.calls[0]['language'], 'ru')
        self.assertEqual(recovery.calls[0]['beam_size'], 3)

    def test_loop_across_segments_is_rejected_even_with_plausible_decoder_scores(self):
        segment, info = response('The same short phrase repeats. ')
        bad = (segment*20, info)
        result = transcribe_microphone(Decoder(bad), range(32000), 'en', Decoder(bad))
        self.assertEqual(result['text'], '')
        self.assertEqual(result['recognitionStatus'], 'unclear')
        self.assertEqual(result['rejectionReason'], 'repetition')

    def test_cancelled_microphone_decode_does_not_start_recovery(self):
        fast = Decoder(response('The same short phrase repeats. '*20))
        recovery = Decoder()
        result = transcribe_microphone(fast, range(32000), 'en', recovery,
                                      cancelled=lambda: bool(fast.calls))
        self.assertIsNone(result)
        self.assertFalse(recovery.calls)


if __name__ == "__main__":
    unittest.main()
