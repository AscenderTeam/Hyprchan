import unittest
import json
import tempfile
from unittest.mock import patch
from desktop_speech_output import (SpeechPhrases, spoken_text, speech_language, transcript_line,
                                   playback_target, playback_properties, voice_enabled,
                                   save_voice_enabled, voice_settings_path)


class SpeechTextTests(unittest.TestCase):
    def test_streamed_actions_are_never_spoken_and_sentences_arrive_before_end(self):
        p = SpeechPhrases()
        self.assertEqual(p.feed("*waves a"), [])
        self.assertEqual(p.feed(" sleeve* Hi!"), ["Hi!"])
        self.assertEqual(p.feed(" I’m already here"), [])
        self.assertEqual(p.feed("~", final=True), ["I’m already here"])

    def test_silence_code_and_markdown_are_not_read_literally(self):
        self.assertEqual(SpeechPhrases().feed("NO_REPLY", final=True), [])
        self.assertEqual(spoken_text("*машу рукавом* **Привет!** ✨"), "Привет!")
        self.assertEqual(spoken_text("See [the page](https://example.com). ```secret code```"), "See the page.")
        self.assertEqual(SpeechPhrases().feed("*only an action*", final=True), [])

    def test_long_text_flushes_without_waiting_for_a_final_period(self):
        p = SpeechPhrases()
        text = "A lovely little sentence with several words " * 6
        chunks = p.feed(text)
        self.assertTrue(chunks)
        chunks += p.feed(final=True)
        self.assertEqual(" ".join(chunks), text.strip())
        self.assertTrue(all(len(chunk) <= 150 for chunk in chunks))

    def test_a_whole_tangent_arriving_at_once_preserves_every_word_in_bounded_phrases(self):
        text = 'This deliberately long sentence has many words ' * 30 + '. And another thought!'
        chunks = SpeechPhrases().feed(text, final=True)
        self.assertGreater(len(chunks), 8)
        self.assertTrue(all(len(chunk) <= 150 for chunk in chunks))
        self.assertEqual(' '.join(chunks), text)

    def test_transcripts_show_exact_recognized_text_or_empty_result(self):
        self.assertEqual(transcript_line({"index": 2, "total": 5, "text": "  hello there  "}), "[2/5] hello there")
        self.assertEqual(transcript_line({"index": 1, "total": 1, "text": ""}), "[1/1] No clear speech recognized")
        self.assertEqual(transcript_line({"index": 1, "total": 5, "text": "Hello!", "language": "en"}), "[1/5] EN · Hello!")
        self.assertEqual(transcript_line({"index": 2, "total": 5, "text": "", "recognitionStatus": "unclear"}),
                         "[2/5] Unclear audio — could not transcribe reliably")
        self.assertEqual(speech_language("Привет, ня!"), "ru")
        self.assertEqual(speech_language("Hi, nyah!"), "en")


class VoiceRoutingTests(unittest.TestCase):
    def test_mute_survives_reopen_and_invalid_settings_stay_muted(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"XDG_CONFIG_HOME": directory}):
            save_voice_enabled(False)
            self.assertFalse(voice_enabled())
            save_voice_enabled(True)
            self.assertTrue(voice_enabled())
            voice_settings_path().write_text("broken")
            self.assertFalse(voice_enabled())

    def test_new_utterance_uses_changed_default_instead_of_startup_speakers(self):
        sinks = json.dumps([
            {"name": "speakers", "properties": {"object.serial": "10"}},
            {"name": "headphones", "properties": {"object.serial": "20"}, "description": "Headphones"}])
        with patch("desktop_speech_output.subprocess.check_output", side_effect=["speakers\n", sinks, "headphones\n", sinks]):
            self.assertEqual(playback_target()[0], "speakers")
            self.assertEqual(playback_target(), ("headphones", "20", "Headphones"))

    def test_missing_headphones_never_resolve_to_speakers_or_query_default(self):
        sinks = json.dumps([{"name": "speakers", "properties": {"object.serial": "10"}}])
        with patch("desktop_speech_output.subprocess.check_output", return_value=sinks) as run:
            with self.assertRaisesRegex(RuntimeError, "stays silent"):
                playback_target("headphones")
            self.assertEqual(run.call_count, 1)
            self.assertNotIn("get-default-sink", run.call_args.args[0])
        properties = playback_properties(locked=True)
        self.assertTrue(properties["node.dont-fallback"])
        self.assertTrue(properties["node.dont-reconnect"])
        self.assertTrue(properties["node.dont-move"])

    def test_system_output_allows_normal_desktop_routing(self):
        properties = playback_properties()
        for key in ("node.dont-fallback", "node.dont-reconnect", "node.dont-move"):
            self.assertFalse(properties.get(key, False))


if __name__ == "__main__":
    unittest.main()
