"""Execute the model's actual cookbook and check its poses on the bundled rig."""
import json
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from hyprchan.core.animations.avatar3d import emote_api
from hyprchan.core.animations.avatar3d.model import AvatarModel
from hyprchan.core.animations.avatar3d.motion import EXPRESSIONS, validate_frame

EXAMPLES = ROOT/'src/hyprchan/assets/avatar3d/emote-examples'
REST = {'leftUpperArm': [0, 0, -72], 'rightUpperArm': [0, 0, 72]}


def sample_example(path):
    """Keep example code unchanged; replace only pacing and the JSON sink."""
    frames, durations = [], []

    def animate(seconds, sample, fps=30):
        durations.append(seconds)
        frames.extend(sample(i/120) for i in range(121))

    def frame(expressions=None, bones=None, hands=None):
        frames.append({'expressions': expressions or {}, 'bones': bones or {}, 'hands': hands or {}})

    with patch.object(emote_api, 'animate', animate), patch.object(emote_api, 'frame', frame), patch('time.sleep'):
        runpy.run_path(str(path), run_name='__main__')
    return frames, durations


class ExampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((EXAMPLES/'manifest.json').read_text())
        cls.samples = {example['id']: sample_example(EXAMPLES/example['file']) for example in cls.manifest}
        cls.model = AvatarModel()

    def test_complete_scripts_execute_without_invalid_or_clipped_frames(self):
        for identity, (frames, durations) in self.samples.items():
            with self.subTest(example=identity):
                self.assertGreater(len(frames), 30)
                for duration in durations:
                    self.assertGreater(duration, 0)
                    self.assertLessEqual(duration, 30)
                for original in frames:
                    validated = validate_frame(original)
                    for channel, values in original.items():
                        self.assertEqual(values, validated[channel], 'example relies on silent clamping')
                # End every reach by lowering the arm, including multistage scripts.
                self.assertTrue(all(target['weight'] < 1e-6 for target in frames[-1].get('hands', {}).values()))

    def test_targets_reach_on_real_skeleton_without_stretching_or_clamping(self):
        for identity, (frames, _) in self.samples.items():
            with self.subTest(example=identity):
                for pose in frames[::3]:
                    world = self.model.posed({**REST, **pose.get('bones', {})}, hands=pose.get('hands'),root=pose.get('root',[0,0,0]))
                    self.assertTrue(np.isfinite(world).all())
                    for side, diagnostic in self.model.hand_diagnostics.items():
                        self.assertFalse(diagnostic['reachClamped'], (identity, diagnostic))
                        self.assertLess(diagnostic['errorMm'], .1, (identity, diagnostic))
                        for a, b in [('UpperArm', 'LowerArm'), ('LowerArm', 'Hand')]:
                            ia, ib = self.model.bones[side+a], self.model.bones[side+b]
                            actual = np.linalg.norm(world[ia][:3, 3]-world[ib][:3, 3])
                            rest = np.linalg.norm(self.model.bind_world[ia][:3, 3]-self.model.bind_world[ib][:3, 3])
                            self.assertAlmostEqual(actual, rest, places=5)

    def test_catalogue_demonstrates_every_expression_shape_space_and_both_hands(self):
        expressions, shapes, spaces, sides, finger_bones = set(), set(), set(), set(), set()
        both_hands = False
        for frames, _ in self.samples.values():
            for frame in frames:
                expressions.update(name for name, value in frame.get('expressions', {}).items() if value >= .1)
                finger_bones.update(set(frame.get('bones', {})) & emote_api.FINGER_BONES)
                hands = {side: target for side, target in frame.get('hands', {}).items() if target['weight'] > .9}
                both_hands |= len(hands) == 2
                sides.update(hands)
                shapes.update(target['shape'] for target in hands.values())
                spaces.update(target['space'] for target in hands.values())
        self.assertEqual(expressions, set(EXPRESSIONS) | {'blush', 'puff'})
        self.assertEqual(shapes, emote_api.HAND_SHAPES)
        self.assertEqual(spaces, {'face', 'body', 'world'})
        self.assertEqual(sides, {'left', 'right'})
        self.assertTrue(both_hands)
        for finger in emote_api.FINGERS:
            self.assertTrue(any(finger in name for name in finger_bones), finger)


if __name__ == '__main__':
    unittest.main()
