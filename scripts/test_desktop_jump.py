"""Jump the actual humanoid rig, retain targets and always return to ground."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from hyprchan.core.animations.avatar3d.emote_api import hand_target, jump
from hyprchan.core.animations.avatar3d.model import AvatarModel
from hyprchan.core.animations.avatar3d.motion import AvatarMotion, validate_frame
from hyprchan.core.animations.avatar3d.wardrobe import add_hoodie

REST = {'leftUpperArm':[0,0,-72],'rightUpperArm':[0,0,72]}


class JumpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=AvatarModel()
        add_hoodie(cls.model)

    def test_hips_translate_every_skin_joint_including_cloth_and_hair(self):
        model=self.model
        before=model.posed(REST)
        after=model.posed(REST,root=[0,.12,0])
        for joints,_ in model.skins:
            for index in joints:
                # Float32 contact iterations can differ slightly after a global
                # shift; keep attachment drift below a tenth of a millimetre.
                np.testing.assert_allclose(after[index][:3,3]-before[index][:3,3],[0,.12,0],atol=1e-4)
                np.testing.assert_allclose(after[index][:3,:3],before[index][:3,:3],atol=1e-3)

    def test_face_target_follows_jump_but_world_target_stays_anchored(self):
        model=self.model
        for space,position in [('face',[0,-.025,.14]),('world',[0,1.43,.16])]:
            points=[]
            for lift in (0,.12):
                world=model.posed(REST,hands={'right':hand_target(position,space=space)},root=[0,lift,0])
                diagnostic=model.hand_diagnostics['right']
                self.assertFalse(diagnostic['reachClamped'])
                self.assertLess(diagnostic['errorMm'],.1)
                points.append((world[model.bones['rightHand']][:3,3]+
                               world[model.bones['rightMiddleProximal']][:3,3])/2)
            np.testing.assert_allclose(np.array(points[1])-points[0],
                                       [0,.12 if space=='face' else 0,0],atol=2e-4)

    def test_jump_has_crouch_lift_landing_and_stop_never_leaves_it_airborne(self):
        for text in ('*jumps with joy*','*подпрыгиваю*','*hops excitedly*'):
            motion=AvatarMotion()
            self.assertEqual(motion.react(text),'jump')
        motion=AvatarMotion();motion.play('jump',duration=3)
        motion.last_sample=motion.emote_at
        heights=[]
        for i in range(211):
            motion.sample(motion.emote_at+i/60)
            heights.append(motion.root[1])
        self.assertLess(min(heights),-.02)
        self.assertGreater(max(heights),.075)
        self.assertLess(abs(heights[-1]),.0001)
        self.assertIsNone(motion.emote)
        motion.set_frame(jump(.4));motion.sample(motion.last_sample+.05)
        self.assertGreater(motion.root[1],.04)
        motion.stop();motion.sample(motion.last_sample+.05)
        self.assertEqual(motion.root,[0,0,0])
        self.assertEqual(motion.headroom,0)

    def test_jump_frames_are_continuous_and_bad_root_values_are_rejected(self):
        frames=[validate_frame(jump(i/1000)) for i in range(1001)]
        lifts=np.array([f['root'][1] for f in frames])
        self.assertLess(np.abs(np.diff(lifts)).max(),.003)
        self.assertEqual(frames[0]['root'],[0,0,0])
        self.assertEqual(frames[-1]['root'],[0,0,0])
        for root in ([0,float('nan'),0],[0,float('inf'),0],[0,.3,0],[0,0],[0,-.11,0]):
            with self.assertRaises(ValueError): validate_frame({'root':root})
        self.assertEqual(validate_frame({})['root'],[0,0,0])


if __name__=='__main__':unittest.main()
