import unittest
from desktop_speech_output import SpeechPhrases, spoken_text, speech_language, transcript_line


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

    def test_transcripts_show_exact_recognized_text_or_empty_result(self):
        self.assertEqual(transcript_line({"index": 2, "total": 5, "text": "  hello there  "}), "[2/5] hello there")
        self.assertEqual(transcript_line({"index": 1, "total": 1, "text": ""}), "[1/1] No clear speech recognized")
        self.assertEqual(transcript_line({"index": 1, "total": 5, "text": "Hello!", "language": "en"}), "[1/5] EN · Hello!")
        self.assertEqual(transcript_line({"index": 2, "total": 5, "text": "", "recognitionStatus": "unclear"}),
                         "[2/5] Unclear audio — could not transcribe reliably")
        self.assertEqual(speech_language("Привет, ня!"), "ru")
        self.assertEqual(speech_language("Hi, nyah!"), "en")


if __name__ == "__main__":
    unittest.main()
