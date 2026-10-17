"""Joint contact keeps the authored attachment, lengths and finite transforms."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from hyprchan.core.animations.avatar3d.model import AvatarModel
from hyprchan.core.animations.avatar3d.wardrobe import add_hoodie
from hyprchan.core.animations.avatar3d.emote_api import hand_target
from hyprchan.core.animations.avatar3d.hair_mesh import refine_hair


class HairRigTest(unittest.TestCase):
    def test_refinement_preserves_surface_uvs_and_normalized_skin_weights(self):
        positions=np.array([[0,1.1,0],[.04,1.1,0],[0,1.13,0]],dtype=np.float32)
        primitive={'material':{'name':'Fixture_HAIR'},'targets':[],
                   'indices':np.array([0,1,2],dtype=np.uint32),
                   'attributes':{'POSITION':positions.copy(),
                                 'NORMAL':np.tile([0,0,1.],(3,1)),
                                 'TEXCOORD_0':positions[:,:2].copy(),
                                 'JOINTS_0':np.array([[0,1,2,3],[1,2,3,4],[2,3,4,5]]),
                                 'WEIGHTS_0':np.tile([.4,.3,.2,.1],(3,1))}}
        refine_hair(SimpleNamespace(primitives=[primitive]))
        a=primitive['attributes'];faces=a['POSITION'][primitive['indices'].reshape(-1,3)]
        normals=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
        self.assertGreater(len(faces),1)
        self.assertTrue((normals[:,2]>0).all())
        self.assertAlmostEqual(float(normals[:,2].sum()),.04*.03,places=7)
        self.assertLessEqual(float(np.linalg.norm(faces-np.roll(faces,1,axis=1),axis=2).max()),.009001)
        np.testing.assert_allclose(a['TEXCOORD_0'],a['POSITION'][:,:2],atol=1e-6)
        np.testing.assert_allclose(a['WEIGHTS_0'].sum(axis=1),1,atol=1e-6)
        np.testing.assert_allclose(np.linalg.norm(a['NORMAL'],axis=1),1,atol=1e-6)
        self.assertTrue(np.isin(a['JOINTS_0'],range(6)).all())

    def test_contact_bends_chains_without_moving_anchors_or_stretching_bones(self):
        model=AvatarModel();add_hoodie(model)
        springs=[s['joints'] for s in model.document['extensions']['VRMC_springBone']['springs']
                 if s.get('name')=='Hair' and len(s['joints'])>=4]
        for head,hands in [([0,0,0],{}),([25,0,0],{}),([8,40,12],{}),
                           ([0,0,0],{'right':hand_target(),'left':hand_target([.085,-.07,.13])})]:
            angles={'head':head,'leftUpperArm':[0,0,-72],'rightUpperArm':[0,0,72]}
            model.hoodie_contact=False
            before=model.posed(angles,hands=hands)
            model.hoodie_contact=True
            after=model.posed(angles,hands=hands)
            moved=0
            for joints in springs:
                root=joints[0]['node']
                np.testing.assert_allclose(after[root][:3,3],before[root][:3,3],atol=1e-6)
                for joint,child in zip(joints,joints[1:]):
                    a,b=joint['node'],child['node']
                    expected=np.linalg.norm(before[b][:3,3]-before[a][:3,3])
                    actual=np.linalg.norm(after[b][:3,3]-after[a][:3,3])
                    self.assertAlmostEqual(actual,expected,places=5)
                    moved+=np.linalg.norm(after[b][:3,3]-before[b][:3,3])>.005
            self.assertGreater(moved,0)
            self.assertTrue(np.isfinite(after).all())


if __name__=='__main__':unittest.main()
