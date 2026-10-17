"""Reach and finger checks against the actual bundled skeleton, not mocks."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from hyprchan.core.animations.avatar3d.model import AvatarModel
from hyprchan.core.animations.avatar3d.motion import AvatarMotion, validate_frame
from hyprchan.core.animations.avatar3d.emote_api import hand_target

REST = {'leftUpperArm':[0,0,-72], 'rightUpperArm':[0,0,72]}


class SpatialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.model = AvatarModel()

    def test_both_palms_reach_face_with_head_and_torso_turns(self):
        m = self.model
        for side in ('left','right'):
            for head in ([0,0,0], [10,35,-15], [-12,-35,18]):
                for chest in ([0,0,0], [5,20,8]):
                    with self.subTest(side=side,head=head,chest=chest):
                        offset = np.array([-.025,-.025,.14])
                        world = m.posed({**REST,'head':head,'chest':chest},
                            hands={side:hand_target(offset,shape='peace',roll=12)})
                        hand = world[m.bones[side+'Hand']]
                        middle = world[m.bones[side+'MiddleProximal']]
                        palm = (hand[:3,3]+middle[:3,3])/2
                        head_i = m.bones['head']
                        head_delta = world[head_i] @ np.linalg.inv(m.bind_world[head_i])
                        face = m.bind_world[head_i][:3,3]+[0,.065,.100]
                        expected = (head_delta @ np.append(face+offset,1))[:3]
                        np.testing.assert_allclose(palm,expected,atol=2e-5)
                        report = m.hand_diagnostics[side]
                        self.assertFalse(report['reachClamped'])
                        self.assertLess(report['errorMm'],.1)
                        np.testing.assert_allclose(report['palmFromFace'],offset,atol=.0001)
                        # Actual lengths stay rigid; no stretching the mesh to cheat.
                        for a,b in (('UpperArm','LowerArm'),('LowerArm','Hand')):
                            ia,ib=m.bones[side+a],m.bones[side+b]
                            self.assertAlmostEqual(np.linalg.norm(world[ia][:3,3]-world[ib][:3,3]),
                                np.linalg.norm(m.bind_world[ia][:3,3]-m.bind_world[ib][:3,3]),places=5)

    def test_peace_raises_two_fingers_and_folds_the_other_two(self):
        m = self.model
        for side in ('left','right'):
            world=m.posed(REST,hands={side:hand_target(shape='peace')})
            inverse=np.linalg.inv(world[m.bones[side+'Hand']])
            sign=1 if side=='left' else -1
            for finger in ('Index','Middle','Ring','Little'):
                proximal=(inverse @ world[m.bones[side+finger+'Proximal']])[:3,3]
                distal=(inverse @ world[m.bones[side+finger+'Distal']])[:3,3]
                extension=(distal-proximal)[0]*sign
                if finger in ('Index','Middle'): self.assertGreater(extension,.045)
                else: self.assertLess(extension,.005)

    def test_zero_weight_unreachable_targets_and_intermediate_reaches(self):
        m=self.model
        base=m.posed(REST)
        np.testing.assert_allclose(m.posed(REST,hands={'right':hand_target(weight=0)}),base)
        for weight in (.01,.1,.25,.5,.75,1):
            world=m.posed(REST,hands={'right':hand_target(weight=weight,roll=180)})
            self.assertTrue(np.isfinite(world).all())
            self.assertLess(m.hand_diagnostics['right']['errorMm'],.1)
        world=m.posed(REST,hands={'right':hand_target([2,2,2])})
        self.assertTrue(np.isfinite(world).all())
        self.assertTrue(m.hand_diagnostics['right']['reachClamped'])
        self.assertGreater(m.hand_diagnostics['right']['errorMm'],100)

    def test_invalid_targets_fail_instead_of_silently_ignoring_them(self):
        for bad in ({'position':[0,1]}, {'position':[0,0,float('nan')]},
                    {'position':[0,0,.1],'shape':'victory'}, {'position':[0,0,.1],'space':'screen'},
                    {'position':[0,0,.1],'strength':1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_frame({'hands':{'right':bad}})
        with self.assertRaises(ValueError): validate_frame({'hand':{}})
        frame=validate_frame({'bones':{'rightIndexProximal':[0,10,5]},
                              'hands':{'right':hand_target(shape='peace')}})
        self.assertEqual(frame['hands']['right']['shape'],'peace')

    def test_tool_pose_is_not_replaced_by_late_roleplay_fallback(self):
        motion=AvatarMotion()
        motion.set_frame({'hands':{'right':hand_target()}})
        motion.script_frame=None  # script finished before the final text arrived
        self.assertIsNone(motion.react('*wave in front of my face*',tool_played=True))
        self.assertIsNone(motion.emote)
        self.assertEqual(motion.react('*wave in front of my face*'),'wave_front')
        self.assertEqual(motion.react('*показываю ✌*'),'peace')
        self.assertEqual(motion.react('*peace sign in front of my face*'),'peace')

    def test_targets_fade_out_and_stop_resets_them(self):
        motion=AvatarMotion()
        motion.set_frame({'hands':{'right':hand_target()}})
        now=motion.last_sample
        for i in range(1,30): motion.sample(now+i*.03)
        self.assertGreater(motion.hand_targets['right']['weight'],.99)
        motion.script_frame=None
        for i in range(30,60): motion.sample(now+i*.03)
        self.assertFalse(motion.hand_targets)
        motion.set_frame({'hands':{'right':hand_target()}})
        motion.sample(now+1.9)
        motion.stop()
        self.assertFalse(motion.hand_targets)


if __name__=='__main__': unittest.main()
