"""Costume geometry, independent rigging and persisted appearance regressions."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from hyprchan.core.animations.avatar3d.appearance import read_appearance, save_appearance
from hyprchan.core.animations.avatar3d.model import AvatarModel
from hyprchan.core.animations.avatar3d.costume import add_costume


def skinned_triangles(model, parts, world):
    result=[]
    for part in parts:
        a=part['attributes'];joints,inverse=model.skins[part['skin']]
        palette=np.array([world[j]@inv for j,inv in zip(joints,inverse)])
        p=np.column_stack([a['POSITION'],np.ones(len(a['POSITION']))])
        p=np.einsum('nkij,nj,nk->ni',palette[a['JOINTS_0'].astype(int)],p,a['WEIGHTS_0'])[:,:3]
        result.append(p[part['indices'].reshape(-1,3)])
    return np.concatenate(result)


class AppearanceTest(unittest.TestCase):
    def test_legacy_malformed_and_unknown_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'appearance.json'
            self.assertEqual(read_appearance(path),('pixel','hoodie'))
            path.write_text('{"mode":"3d"}')
            self.assertEqual(read_appearance(path),('3d','hoodie'))
            for content in ('null','[]','{','{"mode":{},"outfit":[]}'):
                path.write_text(content)
                self.assertEqual(read_appearance(path),('pixel','hoodie'))
            path.write_text('{"mode":"3d","outfit":"removed_costume"}')
            self.assertEqual(read_appearance(path),('3d','hoodie'))

    def test_pixel_switch_keeps_the_chosen_costume(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'hyprchan/appearance.json'
            for mode in ('3d','pixel','3d'):
                save_appearance(path,mode,'cyan_yellow')
                self.assertEqual(read_appearance(path),(mode,'cyan_yellow'))
            with self.assertRaises(ValueError): save_appearance(path,'3d','bad')
            self.assertEqual(read_appearance(path),('3d','cyan_yellow'))


class CostumeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=AvatarModel()
        add_costume(cls.model)
        cls.parts=[p for p in cls.model.primitives if p['material']['name'].startswith('Costume')]

    def test_buffers_are_valid_for_native_gl_and_skinning(self):
        self.assertTrue(self.parts)
        skin=next(p for p in self.model.primitives if p['material']['name']=='Body_00_SKIN')
        for part in [*self.parts,skin]:
            with self.subTest(material=part['material']['name']):
                a=part['attributes']; indices=part['indices']
                self.assertEqual(indices.dtype,np.uint32)
                self.assertTrue(indices.flags.c_contiguous)
                self.assertLess(int(indices.max()),len(a['POSITION']))
                for values in a.values(): self.assertTrue(np.isfinite(values).all())
                np.testing.assert_allclose(a['WEIGHTS_0'].sum(1),1,atol=1e-6)
                self.assertGreaterEqual(float(a['WEIGHTS_0'].min()),0)
                np.testing.assert_array_equal(a['JOINTS_0'],a['JOINTS_0'].astype(int))
                self.assertLess(int(a['JOINTS_0'].max()),len(self.model.skins[part['skin']][0]))

    def test_exposed_neck_and_shoulders_have_no_open_seam(self):
        from hyprchan.core.animations.avatar3d.skin_yoke import boundary_loops
        body=next(p for p in self.model.primitives if p['material']['name']=='Body_00_SKIN')
        a=body['attributes'];p=a['POSITION']
        for loop in boundary_loops(a,body['indices']):
            # Head/face and the covered lower torso have intentional openings.
            # The old flat cut left a fourth opening across the visible yoke.
            if p[loop,1].min()<1.34:
                self.assertLess(float(p[loop,1].max()),1.245)

    def test_front_bodice_has_a_neck_opening_and_moderate_depth(self):
        body=next(p for p in self.parts if p['material']['name']=='Costume bodice')
        p=body['attributes']['POSITION']
        center=p[(abs(p[:,0])<.008)&(p[:,2]>.025)]
        self.assertLess(float(center[:,1].max()),1.275)
        self.assertGreater(float(p[:,2].max()),.12)
        self.assertLess(float(p[:,2].max()),.18)

    def test_raising_an_arm_moves_sleeve_but_not_the_sewn_bodice(self):
        rest=self.model.posed({})
        raised=self.model.posed({'leftUpperArm':[0,0,-75], 'leftLowerArm':[0,-50,0]})
        def positions(part,world):
            joints,inverse=self.model.skins[part['skin']]
            palettes=np.array([world[j]@inv for j,inv in zip(joints,inverse)])
            a=part['attributes']; used=np.unique(part['indices'])
            p=np.column_stack([a['POSITION'][used],np.ones(len(used))])
            return np.einsum('nkij,nj,nk->ni',palettes[a['JOINTS_0'][used].astype(int)],p,a['WEIGHTS_0'][used])[:,:3]
        for part in self.parts:
            name=part['material']['name']
            if name in {'Costume bodice','Costume bow','Costume side panels'}:
                np.testing.assert_allclose(positions(part,rest),positions(part,raised),atol=1e-6,err_msg=name)
            elif name=='Costume collar':
                # The front lapels stay sewn to the bodice; the rear fold
                # follows the shoulders instead of allowing skin through it.
                used=np.unique(part['indices']);p=part['attributes']['POSITION'][used]
                front=(p[:,2]>.045)&(p[:,1]<1.29)
                np.testing.assert_allclose(positions(part,rest)[front],positions(part,raised)[front],atol=1e-6)
            elif name=='Costume sleeves':
                self.assertGreater(float(np.linalg.norm(positions(part,raised)-positions(part,rest),axis=1).max()),.25)

    def test_pins_remain_and_hoodie_accessories_are_not_on_second_costume(self):
        names={p['material']['name'] for p in self.model.primitives}
        self.assertTrue({'Sunshine clip','Hyprland pin cord'}.issubset(names))
        self.assertFalse(any(name.startswith('Hoodie') for name in names))

    def test_neck_ribbon_clears_skin_while_turning_and_nodding(self):
        from bench_avatar_collision import surface_crossings
        skin=[p for p in self.model.primitives if p['material']['name'] in {'Body_00_SKIN','Face_00_SKIN'}]
        ribbon=[p for p in self.parts if p['material']['name'] in {'Costume neck ribbon','Costume neck edging','Costume neck charm'}]
        band=next(p for p in ribbon if p['material']['name']=='Costume neck ribbon')
        # A visible skin gap below the chin, rather than the old rigid ring
        # that reached into the jaw and used a single neck-bone influence.
        self.assertLess(float(band['attributes']['POSITION'][:,1].max()),1.344)
        for pose in ({},{'head':[25,0,0]},{'head':[-18,15,0]},
                     {'head':[8,40,12]},{'head':[8,-40,-12]},
                     {'neck':[12,20,8],'head':[10,-15,0]},
                     {'leftUpperArm':[0,0,-75],'rightUpperArm':[0,0,75]}):
            with self.subTest(pose=pose):
                world=self.model.posed(pose)
                surface=skinned_triangles(self.model,skin,world)
                result=surface_crossings(skinned_triangles(self.model,ribbon,world),surface,np.full(len(surface),'skin'))
                self.assertEqual(result['crossings'],0,result)

    def test_white_collar_and_trim_clear_neck_and_shoulders(self):
        from bench_avatar_collision import surface_crossings
        skin=[p for p in self.model.primitives if p['material']['name'] in {'Body_00_SKIN','Face_00_SKIN'}]
        collar=[p for p in self.parts if p['material']['name'] in {'Costume collar','Costume collar trim','Costume stitching'}]
        self.assertLess(max(float(p['attributes']['POSITION'][:,1].max()) for p in collar),1.32)
        for pose in ({},{'head':[25,0,0]},{'head':[-18,15,0]},
                     {'head':[8,40,12]},{'head':[8,-40,-12]},
                     {'neck':[12,20,8],'head':[10,-15,0]},
                     {'leftUpperArm':[0,0,-75],'rightUpperArm':[0,0,75]},
                     {'leftUpperArm':[0,0,-40],'rightUpperArm':[0,0,40]}):
            with self.subTest(pose=pose):
                world=self.model.posed(pose)
                surface=skinned_triangles(self.model,skin,world)
                result=surface_crossings(skinned_triangles(self.model,collar,world),surface,np.full(len(surface),'skin'))
                self.assertEqual(result['crossings'],0,result)


if __name__=='__main__': unittest.main()
