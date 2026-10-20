"""Front/back depths of the posed torso for residual hair ribbon clearance.

The joint solver handles the broad bends and sleeve contact. This small GPU
pass fits the remaining ribbon thickness to the actual hoodie surface.
"""
import numpy as np
from OpenGL import GL as gl

MINIMUM = np.array([-.7, .80, -.55], dtype=np.float32)
MAXIMUM = np.array([.7, 1.78, .60], dtype=np.float32)
TILE = 512


def projections():
    """Front and back share X/Y, with the nearest surface in each direction."""
    span = MAXIMUM-MINIMUM
    center = (MAXIMUM+MINIMUM)/2
    result = []
    for axis, sign in [(2, -1), (2, 1)]:
        horizontal = 0 if axis == 2 else 2
        matrix = np.zeros((4, 4), dtype=np.float32)
        matrix[0, horizontal] = 2/span[horizontal]
        matrix[0, 3] = -2*center[horizontal]/span[horizontal]
        matrix[1, 1] = 2/span[1]
        matrix[1, 3] = -2*center[1]/span[1]
        matrix[2, axis] = sign*2/span[axis]
        matrix[2, 3] = -sign*2*center[axis]/span[axis]
        matrix[3, 3] = 1
        result.append(matrix)
    return result


class HairCollision:
    def __init__(self):
        self.projections = projections()
        self.texture = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_DEPTH_COMPONENT24, TILE*2, TILE,
                        0, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT, None)
        for setting in (gl.GL_TEXTURE_MIN_FILTER, gl.GL_TEXTURE_MAG_FILTER):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, setting, gl.GL_LINEAR)
        for setting in (gl.GL_TEXTURE_WRAP_S, gl.GL_TEXTURE_WRAP_T):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, setting, gl.GL_CLAMP_TO_EDGE)
        self.framebuffer = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.framebuffer)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                 gl.GL_TEXTURE_2D, self.texture, 0)
        gl.glDrawBuffer(gl.GL_NONE); gl.glReadBuffer(gl.GL_NONE)
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            self.close()
            raise RuntimeError('Hair collision framebuffer is incomplete')

    def render(self, avatar):
        u = avatar.uniforms
        gl.glActiveTexture(gl.GL_TEXTURE3)
        # Never sample the texture attached to the framebuffer being written.
        gl.glBindTexture(gl.GL_TEXTURE_2D, avatar.textures[-1])
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.framebuffer)
        gl.glViewport(0, 0, TILE*2, TILE)
        gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glUniform1i(u['shadowPass'], 1)
        gl.glUniform1i(u['collisionPass'], 1)
        gl.glUniform1i(u['outlinePass'], 0)
        for view, projection in enumerate(self.projections):
            gl.glViewport((view % 2)*TILE, (view//2)*TILE, TILE, TILE)
            gl.glUniformMatrix4fv(u['viewProjection'], 1, True, projection)
            for primitive, vao, _, _, _ in avatar.meshes:
                material = primitive['material']
                if primitive['portrait']['kind'] not in {3, 4} or material['name'] in {'Sunshine emblem', 'Hyprchan W'}:
                    continue
                palette = primitive['palette']
                gl.glUniformMatrix4fv(u['bones'], len(palette), True, palette)
                gl.glUniform1i(u['kind'], primitive['portrait']['kind'])
                gl.glUniform1f(u['alphaCutoff'], material.get('alphaCutoff', .05))
                pbr = material.get('pbrMetallicRoughness', {})
                texture = pbr.get('baseColorTexture', {}).get('index', len(avatar.textures)-1)
                gl.glActiveTexture(gl.GL_TEXTURE0)
                gl.glBindTexture(gl.GL_TEXTURE_2D, avatar.textures[texture])
                gl.glUniform4f(u['baseColor'], *pbr.get('baseColorFactor', [1, 1, 1, 1]))
                gl.glBindVertexArray(vao)
                gl.glDrawElements(gl.GL_TRIANGLES, len(primitive['indices']), gl.GL_UNSIGNED_INT, None)
        gl.glActiveTexture(gl.GL_TEXTURE3)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glUniform1i(u['collisionTexture'], 3)
        gl.glUniform3f(u['collisionMin'], *MINIMUM)
        gl.glUniform3f(u['collisionMax'], *MAXIMUM)
        gl.glUniform1i(u['collisionPass'], 0)

    def close(self):
        if self.framebuffer: gl.glDeleteFramebuffers(1, [self.framebuffer])
        if self.texture: gl.glDeleteTextures([self.texture])
        self.framebuffer = self.texture = None
