#!/usr/bin/env python3
"""Native costume switching check with temporary settings and no media/model workers."""
import json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
scratch=tempfile.TemporaryDirectory()
os.environ['XDG_CONFIG_HOME']=scratch.name+'/config'
os.environ['XDG_DATA_HOME']=scratch.name+'/data'
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'src'),str(root/'scripts')]
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk,GLib
from desktop_avatar import DesktopAvatar
from hyprchan.core.animations.avatar3d.appearance import read_appearance
app=Gtk.Application(application_id='org.hyprchan.CostumeCheck')
result={'passed':False,'switches':[]}
def activate(app):
    host=SimpleNamespace(closing=False,model_ready=True,mood_values=[{'f':15,'v':.5,'e':.7,'a':.5}],mood=Gtk.DropDown.new_from_strings(['Calm']))
    host.send=lambda *args:None
    host.position_windows=lambda:False
    host.sprite=Gtk.Label(label='Pixel renderer retained')
    host.overlay=SimpleNamespace(image=Gtk.Label(label='Pixel overlay retained'),stack=Gtk.Box(orientation=Gtk.Orientation.VERTICAL))
    host.overlay.stack.append(host.overlay.image)
    portrait=Gtk.Box(orientation=Gtk.Orientation.VERTICAL);portrait.append(host.sprite)
    portrait.set_hexpand(True);host.overlay.stack.set_hexpand(True)
    box=Gtk.Box();box.append(portrait);box.append(host.overlay.stack)
    win=Gtk.ApplicationWindow(application=app,title='Hyprchan · costume switching check');win.set_default_size(800,650);win.set_child(box)
    avatar=DesktopAvatar(host,portrait);win.present()
    selections=iter([2,1,0,2,0,1,2]);state={'selected':None,'at':0,'frames':[]}
    def step():
        try:
            if state['selected'] is None:
                selected=next(selections,None)
                if selected is None:
                    assert read_appearance(avatar.settings)==('3d','cyan_yellow')
                    assert len(avatar.costume_widgets)==2
                    assert all(w.motion is avatar.motion for pair in avatar.costume_widgets.values() for w in pair)
                    result['passed']=True;print(json.dumps(result),flush=True);host.closing=True;avatar.close();app.quit();return False
                state.update(selected=selected,at=time.monotonic())
                avatar.selector.set_selected(selected)
                return True
            if time.monotonic()-state['at']<.35:return True
            if avatar.mode=='3d' and any(w.get_width()<1 or w.get_height()<1 for w in avatar.widgets):
                win.queue_resize()
                return True
            selected=state['selected']
            mode,outfit=('pixel',avatar.outfit) if selected==0 else ('3d',['hoodie','cyan_yellow'][selected-1])
            assert avatar.mode==mode and avatar.outfit==outfit
            assert read_appearance(avatar.settings)==(mode,outfit)
            child='pixel' if mode=='pixel' else '3d:'+outfit
            assert avatar.portrait_stack.get_visible_child_name()==child
            assert avatar.overlay_stack.get_visible_child_name()==child
            if mode=='3d':
                for widget in avatar.widgets:
                    assert not widget.failed,widget.failed
                    widget.make_current();widget.attach_buffers();widget.render()
                    assert widget.frames>0
                avatar.motion.play('wave_front',duration=3)
            result['switches'].append({'mode':mode,'outfit':outfit,'renderers':len(avatar.widgets)})
            state['selected']=None
            return True
        except Exception as error:
            import traceback;traceback.print_exc();result['error']=str(error);print(json.dumps(result),flush=True);host.closing=True;avatar.close();app.quit();return False
    GLib.timeout_add(150,step)
    GLib.timeout_add_seconds(30,lambda:(app.quit(),False)[1])
app.connect('activate',activate);app.run([])
if not result['passed']:raise SystemExit(1)
