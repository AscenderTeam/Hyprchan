"""The glTF subset used by the bundled VRM: skinning, textures and sparse morphs."""
from __future__ import annotations

import io
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image

ASSET = Path(__file__).resolve().parents[3] / 'assets/avatar3d/rig-base.vrm'
DTYPES = {5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
SIZES = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def rotation(quaternion):
    x, y, z, w = quaternion
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), 0],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), 0],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y), 0],
        [0, 0, 0, 1]], dtype=np.float32)


def euler(degrees):
    x, y, z = np.radians(degrees)
    sx, sy, sz = np.sin([x, y, z]); cx, cy, cz = np.cos([x, y, z])
    return np.array([[cy*cz, cz*sx*sy-cx*sz, sx*sz+cx*cz*sy, 0],
                     [cy*sz, cx*cz+sx*sy*sz, cx*sy*sz-cz*sx, 0],
                     [-sy, cy*sx, cx*cy, 0], [0, 0, 0, 1]], dtype=np.float32)


def node_matrix(node):
    if 'matrix' in node:
        return np.array(node['matrix'], dtype=np.float32).reshape(4, 4).T.copy()
    result = rotation(node.get('rotation', [0, 0, 0, 1]))
    result[:3, :3] *= np.array(node.get('scale', [1, 1, 1]))[None, :]
    result[:3, 3] = node.get('translation', [0, 0, 0])
    return result


def from_to(source, target, weight=1):
    """Shortest arc quaternion, including the opposite-vector case."""
    source = source / max(1e-8, np.linalg.norm(source))
    target = target / max(1e-8, np.linalg.norm(target))
    dot = float(np.clip(source @ target, -1, 1))
    if dot > .999999: return np.eye(3, dtype=np.float32)
    axis = np.cross(source, target)
    if dot < -.999999:
        axis = np.cross(source, [1, 0, 0] if abs(source[0]) < .8 else [0, 1, 0])
    axis /= max(1e-8, np.linalg.norm(axis))
    half = np.arccos(dot) * weight / 2
    return rotation([*(axis*np.sin(half)), np.cos(half)])[:3, :3]


class AvatarModel:
    def __init__(self, path=ASSET):
        data = Path(path).read_bytes()
        if data[:4] != b'glTF' or struct.unpack_from('<I', data, 4)[0] != 2:
            raise ValueError('Avatar must be a binary glTF 2 model')
        size, chunk = struct.unpack_from('<II', data, 12)
        if chunk != 0x4e4f534a:
            raise ValueError('Missing glTF JSON chunk')
        self.document = json.loads(data[20:20+size])
        self.binary = data[28+size:]
        self.cache = {}
        self.nodes = self.document['nodes']
        self.local = [node_matrix(node) for node in self.nodes]
        self.parents = [-1] * len(self.nodes)
        for parent, node in enumerate(self.nodes):
            for child in node.get('children', []): self.parents[child] = parent
        self.order = []
        def visit(index):
            self.order.append(index)
            for child in self.nodes[index].get('children', []): visit(child)
        for index, parent in enumerate(self.parents):
            if parent == -1: visit(index)
        self.bind_world = self.world(self.local)
        self.constraints = [(i, n['extensions']['VRMC_node_constraint']['constraint'])
                            for i, n in enumerate(self.nodes) if 'VRMC_node_constraint' in n.get('extensions', {})]
        self.hair_roots = [spring['joints'][0]['node'] for spring in
                           self.document['extensions'].get('VRMC_springBone', {}).get('springs', [])
                           if spring.get('name') == 'Hair']
        self.vrm = self.document['extensions']['VRMC_vrm']
        self.bones = {name: item['node'] for name, item in self.vrm['humanoid']['humanBones'].items()}
        self.skins = [(skin['joints'], self.accessor(skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1))
                      for skin in self.document['skins']]
        self.images = []
        used_textures = {m.get('pbrMetallicRoughness', {}).get('baseColorTexture', {}).get('index')
                         for m in self.document['materials']}
        self.mask_textures = {m.get('extensions', {}).get('VRMC_materials_mtoon', {})
                              .get('outlineWidthMultiplyTexture', {}).get('index')
                              for m in self.document['materials']} - {None}
        used_textures |= self.mask_textures
        for texture_index, texture in enumerate(self.document['textures']):
            if texture_index not in used_textures:
                self.images.append(None)
                continue
            image = self.document['images'][texture['source']]
            view = self.document['bufferViews'][image['bufferView']]
            start = view.get('byteOffset', 0)
            pixels = Image.open(io.BytesIO(self.binary[start:start+view['byteLength']])).convert('RGBA')
            self.images.append(np.array(pixels))
        self.primitives = []
        for index, node in enumerate(self.nodes):
            if 'mesh' not in node: continue
            mesh = self.document['meshes'][node['mesh']]
            for primitive in mesh['primitives']:
                attributes = {name: self.accessor(accessor).copy() for name, accessor in primitive['attributes'].items()}
                targets = [{name: self.accessor(accessor) for name, accessor in target.items()}
                           for target in primitive.get('targets', [])]
                self.primitives.append({'node': index, 'skin': node.get('skin'), 'attributes': attributes,
                    'indices': self.accessor(primitive['indices']).astype(np.uint32).ravel(),
                    'material': self.document['materials'][primitive['material']], 'targets': targets,
                    'names': mesh.get('extras', {}).get('targetNames', [])})

    def read_view(self, view_index, offset, count, components, dtype):
        view = self.document['bufferViews'][view_index]
        item = np.dtype(dtype)
        start = view.get('byteOffset', 0) + offset
        stride = view.get('byteStride', item.itemsize * components)
        return np.ndarray((count, components), dtype=item, buffer=self.binary,
                          offset=start, strides=(stride, item.itemsize)).copy()

    def accessor(self, index):
        if index in self.cache: return self.cache[index]
        value = self.document['accessors'][index]
        dtype = DTYPES[value['componentType']]; components = SIZES[value['type']]
        if 'bufferView' in value:
            data = self.read_view(value['bufferView'], value.get('byteOffset', 0), value['count'], components, dtype)
        else:
            data = np.zeros((value['count'], components), dtype=dtype)
        if sparse := value.get('sparse'):
            indices = sparse['indices']; values = sparse['values']
            positions = self.read_view(indices['bufferView'], indices.get('byteOffset', 0), sparse['count'], 1,
                                       DTYPES[indices['componentType']]).ravel()
            data[positions] = self.read_view(values['bufferView'], values.get('byteOffset', 0), sparse['count'], components, dtype)
        if value.get('normalized'):
            info = np.iinfo(data.dtype)
            data = np.maximum(-1, data.astype(np.float32) / info.max)
        self.cache[index] = data
        return data

    def world(self, local):
        result = [None] * len(local)
        for index in self.order:
            parent = self.parents[index]
            result[index] = local[index] if parent < 0 else result[parent] @ local[index]
        return result

    def posed(self, angles, hair=(0, 0)):
        local = [matrix.copy() for matrix in self.local]
        for name, degrees in angles.items():
            index = self.bones.get(name)
            if index is None: continue
            basis = self.bind_world[index].copy(); basis[:3, 3] = 0
            local[index] = local[index] @ np.linalg.inv(basis) @ euler(degrees) @ basis
        for index in self.hair_roots:
            basis = self.bind_world[index].copy(); basis[:3, 3] = 0
            local[index] = local[index] @ np.linalg.inv(basis) @ euler([hair[0], 0, hair[1]]) @ basis
        world = self.world(local)
        def update(index):
            parent = self.parents[index]
            world[index] = local[index] if parent < 0 else world[parent] @ local[index]
            for child in self.nodes[index].get('children', []): update(child)
        # The bundled VRM uses aim constraints for sleeves and roll constraints
        # for twist bones. Ignoring these leaves clothing in a T-pose.
        for index, constraint in self.constraints:
            if 'aim' in constraint:
                c = constraint['aim']; axis = np.zeros(3)
                axis['XYZ'.index(c['aimAxis'][-1])] = -1 if c['aimAxis'].startswith('Negative') else 1
                parent = world[self.parents[index]][:3, :3]
                rest = self.local[index][:3, :3]
                turn = from_to(parent @ rest @ axis, world[c['source']][:3, 3]-world[index][:3, 3], c.get('weight', 1))
                local[index][:3, :3] = parent.T @ turn @ parent @ rest
            elif 'roll' in constraint:
                c = constraint['roll']; axis = np.eye(3)['XYZ'.index(c['rollAxis'])]
                rest = self.local[index][:3, :3]; src = c['source']
                delta = rest.T @ local[src][:3, :3] @ self.local[src][:3, :3].T @ rest
                twist = from_to(axis, delta @ axis).T @ delta
                other = np.roll(axis, 1)
                angle = np.arctan2(axis @ np.cross(other, twist @ other), other @ twist @ other)
                local[index][:3, :3] = rest @ rotation([*(axis*np.sin(angle*c.get('weight', 1)/2)),
                                                        np.cos(angle*c.get('weight', 1)/2)])[:3, :3]
            update(index)
        return world
