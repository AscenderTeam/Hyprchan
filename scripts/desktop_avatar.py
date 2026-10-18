"""Optional 3D presentation and emote controls for the existing GTK companion."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

from gi.repository import Gtk, GLib
from hyprchan.core.animations.avatar3d.motion import AvatarMotion, BUILTINS
from hyprchan.core.animations.avatar3d.emotes import EmoteLibrary, EmoteRunner, animation_seconds
from hyprchan.core.animations.avatar3d.appearance import OUTFITS, read_appearance, save_appearance


class DesktopAvatar:
    def __init__(self, host, portrait):
        self.host = host
        self.motion = AvatarMotion()
        self.library = EmoteLibrary()
        self.runner = EmoteRunner()
        self.widgets = []
        self.costume_widgets = {}
        self.mode = 'pixel'
        self.outfit = 'hoodie'
        self.selecting = False
        self.error = None
        self.script_request = None
        self.next_refresh = 0
        self.last_event = None
        self.last_pose = {}
        self.settings = Path(os.getenv('XDG_CONFIG_HOME', str(Path.home()/'.config'))) / 'hyprchan/appearance.json'
        self.portrait_stack = Gtk.Stack()
        self.portrait_stack.set_vexpand(True)
        self.portrait_stack.set_vhomogeneous(False)
        self.portrait_stack.set_hhomogeneous(False)
        portrait.remove(host.sprite)
        self.portrait_stack.add_named(host.sprite, 'pixel')
        portrait.prepend(self.portrait_stack)
        self.overlay_stack = Gtk.Stack()
        self.overlay_stack.set_vexpand(True)
        self.overlay_stack.set_vhomogeneous(False)
        self.overlay_stack.set_hhomogeneous(False)
        host.overlay.stack.remove(host.overlay.image)
        self.overlay_stack.add_named(host.overlay.image, 'pixel')
        host.overlay.stack.append(self.overlay_stack)
        self.selector = Gtk.DropDown.new_from_strings(['Pixel art', *OUTFITS.values()])
        self.selector.set_tooltip_text('Choose pixel art or either 3D costume')
        portrait.append(self.selector)
        self.selector.connect('notify::selected', self.select_appearance)
        self.emote_picker = Gtk.DropDown()
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ('top','bottom','start','end'): getattr(popover_box, 'set_margin_'+side)(10)
        popover_box.append(self.emote_picker)
        popover = Gtk.Popover(); popover.set_child(popover_box)
        controls = Gtk.Box(spacing=6)
        library_button = Gtk.MenuButton(label='Emotes…')
        library_button.set_popover(popover)
        controls.append(library_button)
        play = Gtk.Button(label='Play emote')
        play.connect('clicked', self.play_selected)
        popover_box.append(play)
        stop = Gtk.Button(label='Stop')
        stop.set_tooltip_text('Stop the current executable emote and reset the pose')
        stop.connect('clicked', lambda *_: self.stop())
        controls.append(stop)
        portrait.append(controls)
        scripts = Gtk.Button(label='Emote scripts…')
        scripts.set_tooltip_text('Saved Python scripts · run with your full account permissions')
        scripts.connect('clicked', lambda *_: subprocess.Popen(['xdg-open', str(self.library.directory)],
                                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        popover_box.append(scripts)
        self.label = Gtk.Label(label='Expressions follow her words', xalign=0)
        self.label.set_wrap(True)
        self.label.set_max_width_chars(26)
        self.label.add_css_class('muted')
        portrait.append(self.label)
        self.items = []
        self.refresh()
        saved, outfit = read_appearance(self.settings)
        self.set_mode(saved, outfit)
        GLib.timeout_add(33, self.tick)

    def failed(self, message):
        self.error = message
        GLib.idle_add(self.fallback)

    def fallback(self):
        self.selector.set_selected(0)
        self.label.set_label('3D unavailable: ' + str(self.error)[:180])
        return False

    def select_appearance(self, *_):
        if self.selecting: return
        selected = self.selector.get_selected()
        if selected == 0:
            self.set_mode('pixel')
        elif selected <= len(OUTFITS):
            self.set_mode('3d', list(OUTFITS)[selected-1])

    def set_mode(self, mode, outfit=None):
        if mode not in {'pixel', '3d'}: raise ValueError('Choose pixel or 3d')
        outfit = self.outfit if outfit is None else outfit
        if outfit not in OUTFITS: raise ValueError('Unknown avatar costume')
        if mode == '3d' and outfit not in self.costume_widgets:
            try:
                from hyprchan.core.animations.avatar3d.widget import Avatar3D
                pair = []
                for stack in (self.portrait_stack, self.overlay_stack):
                    widget = Avatar3D(self.motion, self.failed, outfit=outfit)
                    widget.set_size_request(250, 300)
                    stack.add_named(widget, '3d:'+outfit)
                    pair.append(widget)
                self.costume_widgets[outfit] = pair
            except Exception as error:
                self.failed(str(error))
                return
        self.mode = mode
        self.outfit = outfit
        if mode == '3d': self.widgets = self.costume_widgets[outfit]
        child = '3d:'+outfit if mode == '3d' else 'pixel'
        self.portrait_stack.set_visible_child_name(child)
        self.overlay_stack.set_visible_child_name(child)
        selected = 1+list(OUTFITS).index(outfit) if mode == '3d' else 0
        self.selecting = True
        try: self.selector.set_selected(selected)
        finally: self.selecting = False
        try:
            save_appearance(self.settings, mode, outfit)
        except OSError as error:
            self.label.set_label('Could not save appearance: '+str(error))
        self.sync()
        GLib.timeout_add(120, self.host.position_windows)

    def refresh(self):
        items = self.library.list()
        if items != self.items:
            selected = self.items[self.emote_picker.get_selected()]['id'] if self.items and self.emote_picker.get_selected() < len(self.items) else None
            self.items = items
            self.emote_picker.set_model(Gtk.StringList.new([item['title'] for item in items]))
            self.emote_picker.set_selected(next((i for i, item in enumerate(items) if item['id'] == selected), 0))
            self.sync()

    def sync(self):
        if self.host.model_ready:
            self.host.send('model', {'type': 'emote_state', 'mode': self.mode, 'items': self.items,
                                     'outfit': self.outfit, 'lastEvent': self.last_event})

    def play_selected(self, *_):
        self.set_mode('3d')
        try: self.play(self.items[self.emote_picker.get_selected()]['id'])
        except Exception as error: self.label.set_label(str(error))

    def play(self, identity, seconds=None):
        if seconds is None:
            seconds = next((item.get('seconds', 4) for item in self.items if item['id'] == identity), 4)
        seconds = animation_seconds(seconds)
        self.runner.stop()
        self.motion.stop()
        self.last_pose = {}
        if identity in BUILTINS:
            self.motion.play(identity, duration=seconds)
            result = {'started': True, 'id': identity, 'builtin': True, 'seconds': seconds}
        else:
            result = self.runner.play(self.library.path(identity), duration=seconds)
        self.label.set_label('Playing '+next((item['title'] for item in self.items if item['id'] == identity), identity)+f' · {seconds:g}s')
        return {**result, 'visible': self.mode == '3d'}

    def stop(self):
        self.runner.stop()
        self.motion.stop()
        self.label.set_label('Emote stopped')

    def request(self, event):
        try:
            args = event['arguments']
            if event['tool'] == 'emote_create':
                result = self.library.save(args['id'], args['title'], args['description'], args['python_code'], args['seconds'])
                self.refresh()
                result = {'saved': True, **result}
                self.label.set_label('Saved '+args['title'])
                if args.get('play_now'):
                    result.update(self.play(args['id'], args['seconds']))
                    self.script_request = event['requestId']
            elif event['tool'] == 'emote_play':
                result = self.play(args['id'], args['seconds'])
                self.script_request = event['requestId']
            else: raise ValueError('Unknown emote operation')
            self.host.send('model', {'type': 'emote_result', 'requestId': event['requestId'], 'result': result})
            return bool(result.get('started'))
        except Exception as error:
            self.label.set_label('Emote: '+str(error)[:160])
            self.host.send('model', {'type': 'emote_result', 'requestId': event['requestId'], 'error': str(error)})
            return False

    def tick(self):
        if self.host.closing: return False
        self.motion.mood = self.host.mood_values[self.host.mood.get_selected()]
        # Wayland pauses frame callbacks for occluded windows. Keep animation
        # time and completion independent of drawing, without doing GL work.
        self.motion.sample()
        # Keep the most recent fully reached pose, not the fade-out frame.
        if self.runner.identity and self.widgets:
            pose = getattr(getattr(self.widgets[0], 'data', None), 'hand_diagnostics', {})
            reached = {side:value for side,value in pose.items() if value['weight']>.9}
            if reached: self.last_pose = reached
        frame, event = self.runner.poll()
        if frame: self.motion.set_frame(frame)
        if event:
            if self.last_pose: event['hands'] = self.last_pose
            self.last_event = event
            if event['state'] in {'finished', 'error'}:
                self.motion.script_frame = None
                self.label.set_label(('Emote: '+event['error']) if event.get('error') else 'Expressions follow her words')
            self.sync()
        if time.monotonic() >= self.next_refresh:
            self.next_refresh = time.monotonic()+3
            self.refresh()
        return True

    def status(self):
        return {'mode': self.mode, 'outfit': self.outfit, 'error': self.error, 'emotes': len(self.items),
                'script': self.runner.identity, 'lastEvent': self.last_event,
                'builtin': self.motion.emote, 'root': self.motion.root,
                'hands': getattr(getattr(self.widgets[0], 'data', None), 'hand_diagnostics', {}) if self.widgets else {},
                'renderers': [{'frames': w.frames, 'drawMs': round(w.draw_ms, 2), 'error': w.failed} for w in self.widgets]}

    def close(self):
        self.runner.stop()
