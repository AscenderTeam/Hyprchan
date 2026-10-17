"""Playback can buffer a whole phrase; facial motion must still follow time."""
import queue
import threading
import time
import unittest
from unittest.mock import patch

from desktop_tts_worker import SpeechJob, SpeechOutput


class MouthTimingTests(unittest.TestCase):
    def setUp(self):
        self.output = SpeechOutput.__new__(SpeechOutput)
        self.output.running = True
        self.output.lock = threading.RLock()
        self.output.mouth_frames = queue.Queue()
        self.output.current = SpeechJob(1)
        self.events = []
        self.emit = patch('desktop_tts_worker.emit',
                          lambda kind, **data: self.events.append((time.monotonic(), data)))
        self.emit.start()
        self.thread = threading.Thread(target=self.output.animate_mouth)
        self.thread.start()

    def tearDown(self):
        self.output.running = False
        self.output.current.cancelled.set()
        self.thread.join(timeout=1)
        self.emit.stop()
        self.assertFalse(self.thread.is_alive())

    def test_buffered_envelopes_are_spread_over_playback_time(self):
        now = time.monotonic()
        job = self.output.current
        for i in range(6):
            self.output.mouth_frames.put((job, now+.02+i*.04, i/5))
        deadline = now+1
        while len(self.events)<6 and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(len(self.events), 6)
        self.assertGreater(self.events[-1][0]-self.events[0][0], .15)
        self.assertEqual([e['level'] for _, e in self.events], [i/5 for i in range(6)])

    def test_cancelled_envelope_does_not_animate_the_next_reply(self):
        old = self.output.current
        self.output.mouth_frames.put((old, time.monotonic()+10, 1))
        old.cancelled.set()
        new = self.output.current = SpeechJob(2)
        self.output.mouth_frames.put((new, time.monotonic(), .3))
        deadline = time.monotonic()+1
        while not self.events and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual([e['id'] for _, e in self.events], [2])


if __name__ == '__main__':
    unittest.main()
