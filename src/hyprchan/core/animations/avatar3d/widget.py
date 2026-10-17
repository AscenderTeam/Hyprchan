"""Native GTK/OpenGL VTuber portrait: real mesh, blend shapes and skeletal rig."""
from __future__ import annotations

import ctypes
import time
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
from PIL import Image

from .model import AvatarModel, euler
from .motion import AvatarMotion
from .wardrobe import add_hoodie

from .shaders import VERTEX, FRAGMENT
from .materials import portrait_material
from .hair_collision import HairCollision
from .hair_mesh import refine_hair

_model = None


def model():
    global _model
    if _model is None:
        _model = AvatarModel()
        add_hoodie(_model)
        refine_hair(_model)
    return _model


class Avatar3D(Gtk.GLArea):
    def __init__(self, motion=None, on_error=None):
        super().__init__()
        self.motion = motion or AvatarMotion()
        self.on_error = on_error
        self.set_required_version(3, 3)
        self.set_use_es(False)
        self.set_has_depth_buffer(True)
        self.set_auto_render(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.program = None
        self.shadow_fbo = None
        self.shadow_texture = None
        self.hair_collision = None
        self.failed = None
        self.frames = 0
        self.draw_ms = 0
        self.capture_path = None
        self.meshes = []
        self.textures = []
        self.last_tick = 0
        self.yaw = 0
        self.connect('realize', self.initialize)
        self.connect('unrealize', self.cleanup)
        self.connect('render', self.render)
        self.add_tick_callback(self.tick)

    def tick(self, widget, clock):
        stamp = clock.get_frame_time()
        # Both portraits share motion. Hidden pixel mode does no GL work.
        if self.get_mapped() and stamp - self.last_tick >= 30_000:
            self.last_tick = stamp
            self.queue_render()
        return True

    def fail(self, error):
        self.failed = str(error)
        if self.on_error:
            self.on_error(self.failed)

    def initialize(self, *_):
        self.make_current()
        if self.get_error():
            self.fail(self.get_error())
            return
        try:
            self.data = model()
            self.program = compileProgram(compileShader(VERTEX, gl.GL_VERTEX_SHADER), compileShader(FRAGMENT, gl.GL_FRAGMENT_SHADER))
            self.uniforms = {name: gl.glGetUniformLocation(self.program, name) for name in
                             ['bones', 'viewProjection', 'colorTexture', 'baseColor', 'kind', 'blush', 'alphaCutoff',
                              'outlineMask', 'outlinePass', 'outlineWidth', 'outlineColor', 'shadeColor',
                              'rimColor', 'rimPower', 'shadingShift', 'shadingToony', 'viewDirection',
                              'collisionPass', 'shadowPass', 'shadowTexture', 'lightProjection',
                              'collisionTexture', 'collisionMin', 'collisionMax']}
            for index, pixels in enumerate([*self.data.images, np.full((1, 1, 4), 255, dtype=np.uint8)]):
                if pixels is None:
                    self.textures.append(0)
                    continue
                texture = gl.glGenTextures(1); self.textures.append(texture)
                gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
                format_ = gl.GL_RGBA8 if index in self.data.mask_textures else gl.GL_SRGB8_ALPHA8
                gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, format_, pixels.shape[1], pixels.shape[0], 0,
                                gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixels)
                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
                gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            framebuffer = gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)
            self.shadow_texture = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.shadow_texture)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_DEPTH_COMPONENT24, 1024, 1024, 0,
                            gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT, None)
            for setting in (gl.GL_TEXTURE_MIN_FILTER, gl.GL_TEXTURE_MAG_FILTER):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, setting, gl.GL_NEAREST)
            for setting in (gl.GL_TEXTURE_WRAP_S, gl.GL_TEXTURE_WRAP_T):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, setting, gl.GL_CLAMP_TO_EDGE)
            self.shadow_fbo = gl.glGenFramebuffers(1)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.shadow_fbo)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                      gl.GL_TEXTURE_2D, self.shadow_texture, 0)
            gl.glDrawBuffer(gl.GL_NONE); gl.glReadBuffer(gl.GL_NONE)
            complete = gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) == gl.GL_FRAMEBUFFER_COMPLETE
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, framebuffer)
            if not complete: raise RuntimeError('Avatar shadow framebuffer is incomplete')
            self.hair_collision = HairCollision()
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, framebuffer)
            for primitive in self.data.primitives:
                # The custom hoodie replaces the base shirt; legs are outside the portrait.
                if primitive['material']['name'].startswith(('Tops_', 'Bottoms_', 'Shoes_')):
                    continue
                if primitive['material']['name'] == 'Body_00_SKIN':
                    a = primitive['attributes']['POSITION']
                    triangles = primitive['indices'].reshape(-1, 3)
                    # Keep the neck inside the hood and the hands. Hidden body
                    # triangles must not poke through the tailored shoulders.
                    visible = (((a[:, 1] > 1.23) & (np.abs(a[:, 0]) < .102)) |
                               (np.abs(a[:, 0]) > .535))
                    primitive = {**primitive, 'indices': triangles[visible[triangles].all(axis=1)].ravel()}
                a = primitive['attributes']
                packed = np.ascontiguousarray(np.column_stack([a['POSITION'], a['NORMAL'], a['TEXCOORD_0'], a['JOINTS_0'], a['WEIGHTS_0']]), dtype=np.float32)
                vao = gl.glGenVertexArrays(1); vbo = gl.glGenBuffers(1); ebo = gl.glGenBuffers(1)
                gl.glBindVertexArray(vao)
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
                gl.glBufferData(gl.GL_ARRAY_BUFFER, packed.nbytes, packed, gl.GL_DYNAMIC_DRAW)
                gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, ebo)
                gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, primitive['indices'].nbytes, primitive['indices'], gl.GL_STATIC_DRAW)
                for location, size, offset in [(0,3,0),(1,3,12),(2,2,24),(3,4,32),(4,4,48)]:
                    gl.glEnableVertexAttribArray(location)
                    gl.glVertexAttribPointer(location, size, gl.GL_FLOAT, False, 64, ctypes.c_void_p(offset))
                primitive = {**primitive, 'portrait': portrait_material(primitive['material'])}
                self.meshes.append((primitive, vao, vbo, ebo, packed))
            gl.glBindVertexArray(0)
        except Exception as error:
            self.fail(error)

    def cleanup(self, *_):
        self.make_current()
        if self.get_error(): return
        for _, vao, vbo, ebo, _ in self.meshes:
            gl.glDeleteVertexArrays(1, [vao]); gl.glDeleteBuffers(2, [vbo, ebo])
        if self.textures: gl.glDeleteTextures(self.textures)
        if self.program: gl.glDeleteProgram(self.program)
        if self.shadow_fbo: gl.glDeleteFramebuffers(1, [self.shadow_fbo])
        if self.shadow_texture: gl.glDeleteTextures([self.shadow_texture])
        if self.hair_collision: self.hair_collision.close()
        self.hair_collision = None
        self.shadow_fbo = self.shadow_texture = None
        self.meshes = []; self.textures = []; self.program = None

    def capture(self, path):
        self.capture_path = Path(path)
        self.queue_render()
        # Explicit avatar-only capture must also work on an occluded workspace,
        # where the compositor can stop requesting ordinary frames.
        def capture_frame():
            if self.capture_path and self.program and self.get_realized() and not self.failed:
                self.make_current()
                self.attach_buffers()
                self.render()
            return False
        GLib.idle_add(capture_frame)

    def render(self, *_):
        if not self.program or self.failed: return True
        started = time.perf_counter()
        framebuffer = gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)
        try:
            width = max(1, self.get_width()*self.get_scale_factor())
            height = max(1, self.get_height()*self.get_scale_factor())
            gl.glViewport(0, 0, width, height)
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_CULL_FACE)
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA, gl.GL_ONE, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glUseProgram(self.program)
            angles, morphs, blush, puff = self.motion.sample()
            headroom = getattr(self.motion,'headroom',0)
            # Orthographic portrait, chest to the top of the hair. Expand width
            # as needed instead of cropping the head when the user resizes.
            half_y = max(.325, .23 * height / width)+headroom/2
            half_x = half_y * width / height
            projection = np.array([[1/half_x,0,0,0],[0,1/half_y,0,-(1.315+headroom/2)/half_y],
                                   [0,0,-.5,0],[0,0,0,1]], dtype=np.float32)
            projection = projection @ euler([0, self.yaw, 0])
            light = np.array([-.65,.55,.65]); light /= np.linalg.norm(light)
            right = np.cross([0,1,0],light); right /= np.linalg.norm(right)
            up = np.cross(light,right)
            lighting = np.eye(4,dtype=np.float32)
            lighting[:3,:3] = [right/.45,up/.45,-light/.8]
            root = getattr(self.motion,'root',[0,0,0])
            lighting[:3,3] = -lighting[:3,:3] @ (np.array([0,1.28,0])+root)
            gl.glUniformMatrix4fv(self.uniforms['lightProjection'], 1, True, lighting)
            gl.glUniform1i(self.uniforms['shadowTexture'], 2)
            world = self.data.posed(angles, self.motion.hair, self.motion.hand_targets, root=root)
            skins = [np.ascontiguousarray([world[j] @ inv for j, inv in zip(joints, inverse)], dtype=np.float32)
                     for joints, inverse in self.data.skins]
            gl.glUniform1i(self.uniforms['colorTexture'], 0)
            gl.glUniform1i(self.uniforms['outlineMask'], 1)
            view = euler([0, -self.yaw, 0])[:3, :3] @ np.array([0, 0, 1])
            gl.glUniform3f(self.uniforms['viewDirection'], *view)
            gl.glUniform1f(self.uniforms['blush'], blush)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            for primitive, vao, vbo, _, packed in self.meshes:
                a = primitive['attributes']; material = primitive['material']; name = material['name']
                if primitive['targets']:
                    packed[:, :3] = a['POSITION']; packed[:, 3:6] = a['NORMAL']
                    for index, weight in morphs.items():
                        if index >= len(primitive['targets']): continue
                        target = primitive['targets'][index]
                        if 'POSITION' in target: packed[:, :3] += target['POSITION'] * weight
                        if 'NORMAL' in target: packed[:, 3:6] += target['NORMAL'] * weight
                    if puff and name == 'Face_00_SKIN':
                        p = a['POSITION']
                        area = np.exp(-((np.abs(p[:,0])-.05)/.028)**2 - ((p[:,1]-1.405)/.022)**2)
                        packed[:, 0] += np.sign(p[:,0]) * area * .008 * puff
                        packed[:, 2] += area * .012 * puff
                    gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
                    gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, packed.nbytes, packed)
                primitive['palette'] = skins[primitive['skin']] if primitive['skin'] is not None else np.array([world[primitive['node']]])
            self.hair_collision.render(self)
            for shadow in (True, False):
                gl.glUniform1i(self.uniforms['shadowPass'], int(shadow))
                gl.glUniformMatrix4fv(self.uniforms['viewProjection'], 1, True, lighting if shadow else projection)
                gl.glActiveTexture(gl.GL_TEXTURE2)
                gl.glBindTexture(gl.GL_TEXTURE_2D, self.textures[-1] if shadow else self.shadow_texture)
                gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.shadow_fbo if shadow else framebuffer)
                gl.glViewport(0,0,1024 if shadow else width,1024 if shadow else height)
                if shadow:
                    gl.glDisable(gl.GL_BLEND)
                    gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
                    gl.glPolygonOffset(2.0, 4.0)
                    gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
                else:
                    gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
                    gl.glEnable(gl.GL_BLEND)
                for primitive, vao, _, _, _ in self.meshes:
                    material = primitive['material']; palette = primitive['palette']
                    if shadow and material['name'] in {'Sunshine emblem', 'Hyprchan W'}:
                        continue  # Printed fabric decals do not cast floating shadows.
                    gl.glUniformMatrix4fv(self.uniforms['bones'], len(palette), True, palette)
                    pbr = material.get('pbrMetallicRoughness', {})
                    toon = primitive['portrait']
                    source = material.get('extensions', {}).get('VRMC_materials_mtoon', {})
                    texture = pbr.get('baseColorTexture', {}).get('index', len(self.textures)-1)
                    gl.glActiveTexture(gl.GL_TEXTURE0)
                    gl.glBindTexture(gl.GL_TEXTURE_2D, self.textures[texture])
                    mask = source.get('outlineWidthMultiplyTexture', {}).get('index', len(self.textures)-1)
                    gl.glActiveTexture(gl.GL_TEXTURE1)
                    gl.glBindTexture(gl.GL_TEXTURE_2D, self.textures[mask])
                    gl.glUniform4f(self.uniforms['baseColor'], *pbr.get('baseColorFactor', [1,1,1,1]))
                    gl.glUniform1i(self.uniforms['kind'], toon['kind'])
                    gl.glUniform1f(self.uniforms['alphaCutoff'], material.get('alphaCutoff', .05))
                    if shadow:
                        gl.glUniform1i(self.uniforms['outlinePass'], 0)
                        gl.glBindVertexArray(vao)
                        gl.glDrawElements(gl.GL_TRIANGLES, len(primitive['indices']), gl.GL_UNSIGNED_INT, None)
                        continue
                    for uniform, key in [('shadeColor','shade'), ('outlineColor','outline'), ('rimColor','rim')]:
                        gl.glUniform3f(self.uniforms[uniform], *toon[key])
                    for uniform, key in [('shadingShift','shift'), ('shadingToony','toony'), ('rimPower','rim_power'), ('outlineWidth','width')]:
                        gl.glUniform1f(self.uniforms[uniform], toon[key])
                    gl.glBindVertexArray(vao)
                    gl.glUniform1i(self.uniforms['outlinePass'], 0)
                    gl.glDisable(gl.GL_CULL_FACE)
                    gl.glDrawElements(gl.GL_TRIANGLES, len(primitive['indices']), gl.GL_UNSIGNED_INT, None)
                    if toon['width']:
                        gl.glUniform1i(self.uniforms['outlinePass'], 1)
                        gl.glEnable(gl.GL_CULL_FACE)
                        gl.glCullFace(gl.GL_FRONT)
                        gl.glDrawElements(gl.GL_TRIANGLES, len(primitive['indices']), gl.GL_UNSIGNED_INT, None)
            gl.glDisable(gl.GL_CULL_FACE)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindVertexArray(0)
            gl.glUseProgram(0)
            self.frames += 1
            self.draw_ms = (time.perf_counter()-started)*1000
            if self.capture_path:
                pixels = gl.glReadPixels(0, 0, width, height, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
                Image.frombytes('RGBA', (width,height), pixels).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(self.capture_path)
                self.capture_path = None
        except Exception as error:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, framebuffer)
            self.fail(error)
        return True
