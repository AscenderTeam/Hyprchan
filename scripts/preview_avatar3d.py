#!/usr/bin/env python3
"""Render only the avatar (no captures, mic, model requests, or personal data)."""
import argparse
from pathlib import Path
import sys
import os
import subprocess
import json
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gdk
from hyprchan.core.animations.avatar3d.widget import Avatar3D

parser = argparse.ArgumentParser()
parser.add_argument('--capture')
parser.add_argument('--emote', default='happy')
parser.add_argument('--yaw', type=float, default=0)
parser.add_argument('--gallery', help='Render a real-GL expression/angle review gallery into this directory')
parser.add_argument('--script', help='Play an executable Python emote with full account permissions')
args = parser.parse_args()
app = Gtk.Application(application_id='org.hyprchan.AvatarPreview')
outcome = {'complete': not (args.capture or args.gallery)}

def activate(app):
    win = Gtk.ApplicationWindow(application=app, title='Hyprchan · 3D studio')
    win.set_default_size(560, 680)
    css = Gtk.CssProvider()
    css.load_from_data(b'window { background: linear-gradient(145deg, #172632, #273b50 55%, #174c4d); }')
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    avatar = Avatar3D(on_error=lambda error: print('RENDER ERROR:', error, flush=True))
    avatar.yaw = args.yaw
    win.set_child(avatar)
    win.present()
    def render_preview():
        # Wayland can stop frame callbacks for an occluded studio. Keep this
        # bounded review rendering, using the GLArea's real buffers/context.
        if avatar.program and not avatar.failed:
            avatar.make_current()
            avatar.attach_buffers()
            avatar.render()
        return True
    if args.capture or args.gallery: GLib.timeout_add(33,render_preview)
    def size_window():
        try:
            clients = json.loads(subprocess.check_output(['hyprctl','clients','-j']))
            for client in clients:
                if client.get('pid') == os.getpid():
                    address = 'address:'+client['address']
                    for dispatch, value in [('setfloating', address), ('resizewindowpixel', 'exact 480 600,'+address)]:
                        subprocess.run(['hyprctl','dispatch',dispatch,value], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, ValueError, subprocess.SubprocessError): pass
        return False
    GLib.timeout_add(100, size_window)
    avatar.motion.play(args.emote, duration=30)
    if args.script:
        from hyprchan.core.animations.avatar3d.emotes import EmoteRunner
        runner=EmoteRunner()
        avatar.motion.stop()
        def start_script():
            runner.play(Path(args.script).resolve(),30)
            return False
        def read_script():
            frame,event=runner.poll()
            if frame: avatar.motion.set_frame(frame)
            if event and event.get('error'):
                print('SCRIPT ERROR:',event['error'],flush=True); app.quit(); return False
            return True
        GLib.timeout_add(500,start_script)
        GLib.timeout_add(30,read_script)
        app.connect('shutdown',lambda *_:runner.stop())
    if args.gallery:
        directory = Path(args.gallery); directory.mkdir(parents=True, exist_ok=True)
        poses = [('happy',0),('pout',0),('shy',-20),('surprised',0),('laugh',18),('wave',22),('sad',-15),('wink',0),('wave_front',0),('peace',-20)]
        state = {'index': -1, 'at': 0, 'capture': False}
        def next_pose():
            if avatar.failed:
                print(avatar.failed, flush=True); app.quit(); return False
            if state['capture'] and avatar.capture_path is not None: return True
            if state['index'] < 0 or state['capture']:
                state['index'] += 1
                if state['index'] >= len(poses):
                    (directory/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Hyprchan · expression study</title><style>body{background:#142731;color:#e2fff6;font:16px system-ui}main{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}figure{margin:0;background:linear-gradient(140deg,#29394e,#175052);border-radius:18px;overflow:hidden}img{width:100%;display:block}figcaption{padding:12px}</style><h1>Hyprchan · expression study</h1><main>'+''.join(f'<figure><img src="{name}.png"><figcaption>{name} · {yaw}°</figcaption></figure>' for name,yaw in poses)+'</main><p>Customized pixiv VRM base · native GTK / OpenGL render</p>')
                    print({'gallery':str(directory), 'frames':avatar.frames, 'lastDrawMs':avatar.draw_ms}, flush=True)
                    outcome['complete']=True
                    app.quit(); return False
                name, yaw = poses[state['index']]
                avatar.yaw=yaw; avatar.motion.play(name, duration=30)
                state.update(at=time.monotonic(), capture=False)
            elif time.monotonic()-state['at']>.8:
                avatar.capture(directory/f'{poses[state["index"]][0]}.png')
                state['capture']=True
            return True
        GLib.timeout_add(100, next_pose)
        GLib.timeout_add_seconds(30, lambda: (app.quit(), False)[1])
    if args.capture:
        GLib.timeout_add(1800, lambda: (avatar.capture(args.capture), False)[1])
        def finish():
            if not Path(args.capture).exists() and not avatar.failed:
                return True
            print({'frames': avatar.frames, 'drawMs': avatar.draw_ms, 'error': avatar.failed}, flush=True)
            outcome['complete']=not avatar.failed and avatar.capture_path is None
            app.quit()
            return False
        GLib.timeout_add(2300, finish)
        GLib.timeout_add_seconds(15, lambda: (app.quit(), False)[1])

app.connect('activate', activate)
app.run([])
if not outcome['complete']: raise SystemExit('Avatar review did not complete')
