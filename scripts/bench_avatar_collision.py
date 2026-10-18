#!/usr/bin/env python3
"""Read actual GPU hair positions and test them against the posed outfit atlas.

Uses only the bundled avatar and synthetic poses, without mic/camera/model calls.
Vertex positions come from transform feedback, not a reimplementation of GLSL.
Whole triangle surfaces are checked against the actual skinned clothing/neck/hands.
The original scalp/face attachment overlap is counted separately, not called an
outfit collision. This validates the listed poses, not every executable pose.
"""
import argparse
from concurrent.futures import CancelledError, ThreadPoolExecutor
import ctypes
import json
import itertools
import os
import subprocess
from pathlib import Path
import sys
import threading
import time

import numpy as np
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileShader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from hyprchan.core.animations.avatar3d.widget import Avatar3D
from hyprchan.core.animations.avatar3d.shaders import VERTEX
from hyprchan.core.animations.avatar3d.hair_collision import MINIMUM, MAXIMUM
from hyprchan.core.animations.avatar3d.emote_api import hand_target, jump
from hyprchan.core.animations.avatar3d.motion import AvatarMotion


def feedback_program(source):
    shader = compileShader(source, gl.GL_VERTEX_SHADER)
    program = gl.glCreateProgram()
    gl.glAttachShader(program, shader)
    names = (ctypes.c_char_p*1)(b'worldPosition')
    gl.glTransformFeedbackVaryings(program, 1, ctypes.cast(names, ctypes.POINTER(ctypes.POINTER(ctypes.c_char))), gl.GL_INTERLEAVED_ATTRIBS)
    gl.glLinkProgram(program)
    gl.glDeleteShader(shader)
    if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
        raise RuntimeError(gl.glGetProgramInfoLog(program).decode())
    return program


def gpu_hair(avatar, program):
    gl.glUseProgram(program)
    uniform = lambda name: gl.glGetUniformLocation(program, name)
    gl.glUniformMatrix4fv(uniform('viewProjection'), 1, True, np.eye(4, dtype=np.float32))
    gl.glUniform1i(uniform('kind'), 1)
    gl.glUniform1i(uniform('outlinePass'), 0)
    gl.glUniform1i(uniform('shadowPass'), 1)
    gl.glUniform1i(uniform('collisionTexture'), 3)
    gl.glUniform3f(uniform('collisionMin'), *MINIMUM)
    gl.glUniform3f(uniform('collisionMax'), *MAXIMUM)
    avatar.upload_hair_contact(program)
    result = []
    buffer = gl.glGenBuffers(1)
    try:
        gl.glEnable(gl.GL_RASTERIZER_DISCARD)
        for primitive, vao, _, _, packed in avatar.meshes:
            if primitive['portrait']['kind'] != 1: continue
            palette = primitive['palette']
            gl.glUniformMatrix4fv(uniform('bones'), len(palette), True, palette)
            gl.glBindVertexArray(vao)
            gl.glBindBuffer(gl.GL_TRANSFORM_FEEDBACK_BUFFER, buffer)
            size = len(packed)*3*4
            gl.glBufferData(gl.GL_TRANSFORM_FEEDBACK_BUFFER, size, None, gl.GL_STREAM_READ)
            gl.glBindBufferBase(gl.GL_TRANSFORM_FEEDBACK_BUFFER, 0, buffer)
            gl.glBeginTransformFeedback(gl.GL_POINTS)
            gl.glDrawArrays(gl.GL_POINTS, 0, len(packed))
            gl.glEndTransformFeedback()
            data = gl.glGetBufferSubData(gl.GL_TRANSFORM_FEEDBACK_BUFFER, 0, size)
            positions = np.frombuffer(data, dtype=np.float32).reshape(-1, 3).copy()
            movable = primitive['attributes']['POSITION'][:, 1] < 1.455
            faces = primitive['indices'].reshape(-1, 3)
            faces = faces[movable[faces].all(axis=1)]
            result.append((positions[movable], positions[faces]))
    finally:
        gl.glDisable(gl.GL_RASTERIZER_DISCARD)
        gl.glBindBufferBase(gl.GL_TRANSFORM_FEEDBACK_BUFFER, 0, 0)
        gl.glDeleteBuffers(1, [buffer])
        gl.glUseProgram(0)
    return result


def surface_crossings(hair, surface, labels, cancelled=None):
    """Broad-phase grid plus actual triangle/triangle edge intersections.

    Unlike the four-view silhouette, this does not fill the empty space between
    a raised sleeve and the torso. Those false positives are not penetrations.
    """
    cell = .025
    low, high = surface.min(axis=1), surface.max(axis=1)
    grid = {}
    for i, (a, b) in enumerate(zip(np.floor(low/cell).astype(int), np.floor(high/cell).astype(int))):
        if i % 500 == 0 and cancelled is not None and cancelled.is_set():
            raise CancelledError()
        for key in itertools.product(*(range(x, y+1) for x, y in zip(a, b))):
            grid.setdefault(key, []).append(i)
    pairs = []
    for i, triangle in enumerate(hair):
        if i % 500 == 0 and cancelled is not None and cancelled.is_set():
            raise CancelledError()
        lo, hi = triangle.min(axis=0), triangle.max(axis=0)
        candidates = set()
        for key in itertools.product(*(range(x, y+1) for x, y in zip(np.floor(lo/cell).astype(int), np.floor(hi/cell).astype(int)))):
            candidates.update(grid.get(key, ()))
        if not candidates: continue
        ids = np.fromiter(candidates, dtype=int)
        ids = ids[((low[ids] <= hi) & (high[ids] >= lo)).all(axis=1)]
        pairs.extend((i, j) for j in ids)
    if not pairs: return {'pairs': 0, 'crossings': 0, 'materials': {}}
    pairs = np.array(pairs)
    first, second = hair[pairs[:, 0]], surface[pairs[:, 1]]
    hit = np.zeros(len(pairs), dtype=bool)
    for edges, triangles in [(first, second), (second, first)]:
        a, b, c = triangles.transpose(1, 0, 2)
        ab, ac = b-a, c-a
        for i in range(3):
            origin = edges[:, i]; direction = edges[:, (i+1)%3]-origin
            h = np.cross(direction, ac); determinant = np.einsum('ij,ij->i', ab, h)
            inverse = 1/np.where(np.abs(determinant) > 1e-12, determinant, 1)
            s = origin-a
            u = inverse*np.einsum('ij,ij->i', s, h)
            q = np.cross(s, ab)
            v = inverse*np.einsum('ij,ij->i', direction, q)
            t = inverse*np.einsum('ij,ij->i', ac, q)
            hit |= ((np.abs(determinant)>1e-12) & (u>=0) & (v>=0) & (u+v<=1)
                    & (t>.00001) & (t<.99999))
    return {'pairs': len(pairs), 'crossings': int(hit.sum()),
            'materials': {str(name):int((labels[pairs[hit,1]]==name).sum()) for name in np.unique(labels[pairs[hit,1]])},
            'materialBounds': {str(name):[first[hit][labels[pairs[hit,1]]==name].min(axis=(0,1)).round(5).tolist(),
                                          first[hit][labels[pairs[hit,1]]==name].max(axis=(0,1)).round(5).tolist()]
                               for name in np.unique(labels[pairs[hit,1]]) if name!='Face_00_SKIN'},
            'bounds': [first[hit].min(axis=(0,1)).round(4).tolist(), first[hit].max(axis=(0,1)).round(4).tolist()] if hit.any() else None}


def outfit_triangles(avatar):
    result = [];labels=[]
    for primitive, *_ in avatar.meshes:
        if primitive['portrait']['kind'] not in {3,4,8} or primitive['material']['name'] in {'Sunshine emblem','Hyprchan W'}: continue
        a = primitive['attributes']
        positions = np.column_stack([a['POSITION'], np.ones(len(a['POSITION']))])
        matrix = primitive['palette'][a['JOINTS_0'].astype(int)]
        posed = np.einsum('nkij,nj,nk->ni', matrix, positions, a['WEIGHTS_0'])[:, :3]
        result.append(posed[primitive['indices'].reshape(-1,3)])
        labels.extend([primitive['material']['name']]*len(result[-1]))
    return np.concatenate(result),np.array(labels)


class Pose:
    def __init__(self, bones=None, hands=None, root=None):
        self.bones = {'leftUpperArm': [0, 0, -72], 'rightUpperArm': [0, 0, 72], **(bones or {})}
        self.hair = (2, -2)
        self.hand_targets = hands or {}
        self.root = root or [0,0,0]
        self.headroom = max(0,self.root[1])

    def sample(self): return self.bones, {}, 0, 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--poses', nargs='+', help='Only these named synthetic poses')
    parser.add_argument('--outfit', choices=['hoodie', 'cyan_yellow'], default='hoodie')
    args = parser.parse_args()
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    report = {'syntheticOnly': True, 'outfit': args.outfit, 'poses': [], 'reference': 'Same refined mesh with joint contact and cloth clearance disabled',
              'method': 'Actual GPU vertices; triangle intersection with posed surfaces. Authored scalp/Face_00_SKIN overlaps are reported but excluded from the clothing/neck/hands assertion.'}
    app = Gtk.Application(application_id='org.hyprchan.CollisionReview')

    def activate(app):
        window = Gtk.ApplicationWindow(application=app, title='Hyprchan · collision review')
        window.set_default_size(480, 600)
        avatar = Avatar3D(motion=Pose(), outfit=args.outfit)
        window.set_child(avatar); window.present()
        worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='hair-check')
        cancelled = threading.Event()
        programs = []
        finished = False
        heartbeat = {'ticks': 0, 'maxGapMs': 0.0}
        last_tick = None

        def pulse():
            nonlocal last_tick
            if finished: return False
            now = time.perf_counter()
            if last_tick is not None:
                heartbeat['maxGapMs'] = max(heartbeat['maxGapMs'], (now-last_tick)*1000)
            last_tick = now
            heartbeat['ticks'] += 1
            return True

        def finish(error=None):
            nonlocal finished
            if finished: return False
            finished = True
            cancelled.set()
            worker.shutdown(wait=False, cancel_futures=True)
            if error is not None:
                report['error'] = str(error)
                report['passed'] = False
                print(type(error).__name__, str(error), flush=True)
            heartbeat['maxGapMs'] = round(heartbeat['maxGapMs'], 3)
            report['guiHeartbeat'] = heartbeat
            try:
                avatar.make_current()
                for program in programs: gl.glDeleteProgram(program)
            finally:
                output.write_text(json.dumps(report, indent=2)+'\n')
                app.quit()
            return False

        window.connect('close-request', lambda *_: finish(RuntimeError('Review window closed')))

        def size_window():
            try:
                clients=json.loads(subprocess.check_output(['hyprctl','clients','-j']))
                for client in clients:
                    if client.get('pid')==os.getpid():
                        address='address:'+client['address']
                        for command,value in [('setfloating',address),('resizewindowpixel','exact 480 600,'+address)]:
                            subprocess.run(['hyprctl','dispatch',command,value],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except (OSError,ValueError,subprocess.SubprocessError):pass
            return False
        GLib.timeout_add(100,size_window)

        def stages():
            # GTK and OpenGL stay on the main thread. Each yield returns to its
            # event loop; the expensive triangle checks use copied arrays in a
            # worker and never access the widget or its mutable model.
            while not avatar.program and not avatar.failed: yield
            try:
                if avatar.failed: raise RuntimeError(avatar.failed)
                avatar.make_current(); avatar.attach_buffers()
                programs.extend([feedback_program(VERTEX.replace('p.xyz=clearHair(original);', 'p.xyz=original;')),
                                 feedback_program(VERTEX)])
                pulse()
                GLib.timeout_add(100, pulse)
                cases = [
                    ('rest', Pose(), 0), ('side', Pose(), 60), ('back', Pose(), 160),
                    ('left', Pose({'head': [8, 40, 12]}), -35),
                    ('right', Pose({'head': [8, -40, -12]}), 35),
                    ('nod', Pose({'head': [25, 0, 0]}), 45),
                    ('lean', Pose({'head': [-10, 15, 12], 'chest': [5, 18, 10]}), -45),
                    ('nod_mid', Pose({'head': [12, 0, 0]}), 45),
                    ('left_mid', Pose({'head': [4, 20, 6]}), -35),
                    ('right_mid', Pose({'head': [4, -20, -6]}), 35),
                    ('look_up', Pose({'head': [-18, 15, 0]}), -20),
                    ('wave_mid', Pose(hands={'right': hand_target(weight=.5)}), 0),
                    ('wave', Pose(hands={'right': hand_target()}), 0),
                    ('peek_mid', Pose(hands={'right': hand_target([-.085, -.07, .13],weight=.5),
                                        'left': hand_target([.085, -.07, .13],weight=.5)}), 0),
                    ('peek', Pose(hands={'right': hand_target([-.085, -.07, .13]),
                                        'left': hand_target([.085, -.07, .13])}), 0),
                ]
                for name,progress in [('jump_crouch',.20),('jump_apex',.40),('jump_land',.60),('jump_rest',1)]:
                    pose = jump(progress)
                    cases.append((name,Pose(pose['bones'],root=pose['root']),0))
                for name, elapsed in [('heart_hug_raise', .15), ('heart_hug', 1.5), ('heart_hug_lower', 3.85)]:
                    motion = AvatarMotion()
                    motion.react('*прижимаю рукава к груди*')
                    start = motion.emote_at
                    for frame in range(1, round(elapsed*60)+1):
                        bones, *_ = motion.sample(start+frame/60)
                    cases.append((name, Pose(bones, hands=motion.hand_targets), 0))
                if args.poses: cases=[case for case in cases if case[0] in args.poses]
                if not cases: raise ValueError('No matching poses')
                for name, pose, yaw in cases:
                    avatar.motion = pose; avatar.yaw = yaw
                    item = {'pose': name}
                    for label,program in zip(('skinningOnly','contact'),programs):
                        avatar.data.hoodie_contact=label=='contact'
                        avatar.make_current();avatar.attach_buffers()
                        timings=[]
                        for trial in range(7):
                            avatar.make_current();avatar.attach_buffers()
                            started=time.perf_counter();avatar.render();gl.glFinish()
                            if trial>=2:timings.append((time.perf_counter()-started)*1000)
                            yield
                        if avatar.failed:raise RuntimeError(avatar.failed)
                        avatar.make_current();avatar.attach_buffers()
                        geometry=gpu_hair(avatar,program)
                        triangles=np.concatenate([triangles for _,triangles in geometry])
                        pending=worker.submit(surface_crossings,triangles,*outfit_triangles(avatar),cancelled)
                        while not pending.done(): yield
                        result=pending.result()
                        result['outfitAndBodyCrossings']=sum(count for material,count in result['materials'].items() if material!='Face_00_SKIN')
                        result['triangles']=len(triangles)
                        if label=='contact':
                            result['drawMedianMs']=round(float(np.median(timings)),3)
                        item[label]=result
                    report['poses'].append(item)
                    print(json.dumps(item),flush=True)
                    avatar.capture(output.parent/(name+'.png'))
                    avatar.make_current();avatar.attach_buffers();avatar.render()
                    yield
                report['pixels']=[avatar.get_width()*avatar.get_scale_factor(),avatar.get_height()*avatar.get_scale_factor()]
                report['passed']=(all(p['contact']['outfitAndBodyCrossings']==0 for p in report['poses'])
                                  and heartbeat['ticks']>1 and heartbeat['maxGapMs']<1000)
            except Exception as error:
                finish(error)
            else:
                finish()

        pending_stages = stages()

        def step():
            if finished: return False
            try: next(pending_stages)
            except StopIteration: return False
            return True

        GLib.timeout_add(25, step)
        GLib.timeout_add_seconds(180, lambda: finish(TimeoutError('Collision review exceeded 180 seconds')))

    app.connect('activate', activate); app.run([])
    if not report.get('passed'): raise SystemExit('Hair collision verification failed; see report')


if __name__ == '__main__': main()
