import unittest
from desktop_local_voices import BilingualVoice, PCM, speech_spans


class BilingualVoiceTests(unittest.TestCase):
    def test_artist_and_song_names_remain_whole_and_in_order(self):
        text = 'О, у тебя играет GoGo Penguin — «Signal In The Noise»! Ня!'
        self.assertEqual(list(speech_spans(text)), [
            ('ru', 'О, у тебя играет'), ('en', 'GoGo Penguin — «Signal In The Noise»!'), ('ru', 'Ня!')])

    def test_technical_names_numbers_and_accented_latin_are_preserved(self):
        self.assertEqual(list(speech_spans('systemd уже заведует моим сном?! Требую cuddle.target и 2 печеньки.')), [
            ('en', 'systemd'), ('ru', 'уже заведует моим сном?! Требую'),
            ('en', 'cuddle.target'), ('ru', 'и 2 печеньки.')])
        self.assertEqual(list(speech_spans('Björk, ты чудо!')), [('en', 'Björk,'), ('ru', 'ты чудо!')])
        self.assertEqual(list(speech_spans('42')), [('ru', '42')])
        self.assertEqual(list(speech_spans('... — ✨')), [])

    def test_each_phrase_uses_the_selected_voice_without_losing_audio(self):
        calls = []

        class Voice:
            def __init__(self, language): self.language = language
            def synthesize(self, text):
                calls.append((self.language, text))
                yield PCM(24000, text.encode())

        voice = BilingualVoice({language: Voice(language) for language in ('en', 'ru')})
        chunks = list(voice.synthesize('Hi! Привет, GoGo Penguin!'))
        self.assertEqual(calls, [('en', 'Hi!'), ('ru', 'Привет,'), ('en', 'GoGo Penguin!')])
        self.assertEqual([chunk.audio_int16_bytes.decode() for chunk in chunks], [text for _, text in calls])
        self.assertEqual(list(voice.synthesize('Ня!'))[0].audio_int16_bytes.decode(), 'Ня!')

    def test_mismatched_sample_rate_cannot_corrupt_playback(self):
        class WrongRate:
            def synthesize(self, text): yield PCM(22050, b'00')

        voice = BilingualVoice({'en': WrongRate()})
        with self.assertRaisesRegex(RuntimeError, '24000 Hz'):
            list(voice.synthesize('Hello!'))


if __name__ == '__main__':
    unittest.main()
