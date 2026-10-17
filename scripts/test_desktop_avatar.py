"""Protocol, persistence, real-rig and subprocess regression checks."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from hyprchan.core.animations.avatar3d.emotes import EmoteLibrary, EmoteRunner
from hyprchan.core.animations.avatar3d.motion import AvatarMotion, validate_frame


class EmotesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = EmoteLibrary(self.temp.name)
        self.runner = EmoteRunner()

    def tearDown(self):
        self.runner.stop()
        self.temp.cleanup()

    def finish(self, timeout=3):
        deadline = time.monotonic()+timeout
        frames = []
        while time.monotonic() < deadline:
            frame, event = self.runner.poll()
            if frame: frames.append(frame)
            if event and event['state'] in {'finished', 'error'}: return frames, event
            time.sleep(.015)
        self.fail('Emote subprocess did not finish')

    def test_saved_script_survives_library_reopen_and_has_full_python_access(self):
        self.library.save('test_emote', 'Test', 'Synthetic test',
            "from pathlib import Path\nfrom hyprchan.core.animations.avatar3d.emote_api import animate\n"
            "Path('marker').write_text('full Python works')\n"
            "animate(.15, lambda t: {'expressions': {'puff': .8}, 'bones': {'head': [0, 0, 12]}})\n")
        again = EmoteLibrary(self.temp.name)
        self.assertIn('test_emote', [item['id'] for item in again.list()])
        self.runner.play(again.path('test_emote'))
        frames, event = self.finish()
        self.assertEqual(event['state'], 'finished')
        self.assertGreaterEqual(event['frames'], 3)
        self.assertEqual(frames[-1]['expressions']['puff'], .8)
        self.assertEqual((Path(self.temp.name)/'marker').read_text(), 'full Python works')

    def test_bad_update_does_not_destroy_working_source(self):
        self.library.save('saved', 'Saved', '', 'print(1)')
        with self.assertRaises(SyntaxError): self.library.save('saved', 'Broken', '', 'def invalid(')
        self.assertEqual(self.library.path('saved').read_text(), 'print(1)')
        for identity in ('../outside', '/tmp/escape', 'happy'):
            with self.assertRaises(ValueError): self.library.save(identity, 'Bad', '', 'pass')

    def test_deadline_terminates_unresponsive_script(self):
        self.library.save('waiting', 'Waiting', '', 'import time\ntime.sleep(20)\n')
        self.runner.play(self.library.path('waiting'), seconds=1)
        process = self.runner.process
        _, event = self.finish()
        self.assertTrue(event['timedOut'])
        self.assertIsNotNone(process.poll())

    def test_stop_clears_mailbox_and_reaps_process(self):
        self.library.save('waiting', 'Waiting', '', 'import time\ntime.sleep(20)\n')
        self.runner.play(self.library.path('waiting'))
        process = self.runner.process
        self.runner.stop()
        process.wait(timeout=2)
        self.assertIsNone(self.runner.process)
        self.assertIsNone(self.runner.poll()[0])

    def test_invalid_frames_fail_without_crashing_host(self):
        self.library.save('bad_frame', 'Bad frame', '', 'print(\'{"expressions":{"puff":NaN}}\')')
        self.runner.play(self.library.path('bad_frame'))
        _, event = self.finish()
        self.assertEqual(event['state'], 'error')
        self.assertIn('finite', event['error'])
        with self.assertRaises(ValueError): validate_frame({'bones': {'head': [1,2]}})

    def test_speech_amplitude_decays_and_roleplay_triggers_pout(self):
        motion = AvatarMotion()
        self.assertEqual(motion.react('*надуваю щёчки* Уу!'), 'pout')
        motion.voice(.8)
        _, shapes, _, _ = motion.sample(motion.voice_at+.01)
        self.assertGreater(shapes.get(36, 0), 0)
        _, shapes, _, _ = motion.sample(motion.voice_at+.5)
        self.assertEqual(shapes.get(36, 0), 0)

    def test_rig_constraints_move_sleeves_with_arms(self):
        import numpy as np
        from hyprchan.core.animations.avatar3d.model import AvatarModel
        model = AvatarModel()
        world = model.posed({'leftUpperArm': [0,0,-70]})
        index, constraint = next((i,c['aim']) for i,c in model.constraints
                                 if 'aim' in c and model.nodes[i]['name'] == 'J_Aim_L_TopsUpperArm')
        actual = world[index][:3,:3] @ np.array([1,0,0])
        expected = world[constraint['source']][:3,3]-world[index][:3,3]
        expected /= np.linalg.norm(expected)
        self.assertGreater(float(actual @ expected), .999)
        for matrix in world: self.assertTrue(np.isfinite(matrix).all())


if __name__ == '__main__': unittest.main()
