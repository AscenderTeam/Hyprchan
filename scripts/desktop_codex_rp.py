#!/usr/bin/env python3
"""Native Hyprchan preview: sprites, streaming Codex, local STT, and vision.

Run with the system Python (GTK). Speech runs in its own Python environment.
Closing the chat window releases capture devices and shuts down all workers.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
from desktop_speech_output import SpeechPhrases, transcript_line

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.getenv("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hyprchan-codex"
SOCKET = RUNTIME / "desktop.sock"
SPEECH_PYTHON = Path(os.getenv("HYPRCHAN_SPEECH_PYTHON",
                              str(Path.home() / ".local/share/hyprchan-codex/venv/bin/python")))
TTS_PYTHON = Path.home() / ".local/share/hyprchan-codex/tts-expressive/bin/python"


def control(command: dict) -> dict:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(SOCKET))
        client.sendall((json.dumps(command) + "\n").encode())
        return json.loads(client.makefile().readline())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--muted", action="store_true", help="Start with microphone off")
    parser.add_argument("--no-vision", action="store_true", help="Start with camera and screen capture off")
    parser.add_argument("--no-reactions", action="store_true", help="Keep automatic screen reactions off")
    parser.add_argument("--no-memory", action="store_true", help="Keep persistent user memory off")
    parser.add_argument("--no-audio-awareness", action="store_true", help="Keep playback awareness and listen_in off")
    parser.add_argument("--no-voice", action="store_true", help="Keep spoken replies off")
    parser.add_argument("--no-notifications", action="store_true", help="Keep optional desktop notifications off")
    parser.add_argument("--control", help='Send JSON, e.g. {"type":"status"} or {"type":"quit"}')
    args = parser.parse_args()
    if args.control:
        print(json.dumps(control(json.loads(args.control)), ensure_ascii=False, indent=2))
        return 0
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(RUNTIME, 0o700)
    lock = (RUNTIME / "desktop.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        control({"type": "present"})
        return 0

    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, GLib, GLibUnix, Gtk, Pango
    sys.path.insert(0, str(ROOT / "src"))
    from hyprchan.core.animations.renderer.window import HyprchanWindow, PixelArtImage
    from hyprchan.shared.utils.animations import load_animation_frames

    class Desktop(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="org.hyprland.hyprchan.codex")
            self.children = {}
            self.outgoing = {}
            self.closing = False
            self.model_ready = False
            self.speech_ready = False
            self.vision_ready = False
            self.vision_wanted = not args.no_vision
            self.vision_active = False
            self.vision_generation = 0
            self.latest_visual = None
            self.reactions_wanted = not args.no_reactions
            self.memory_wanted = not args.no_memory
            self.audio_wanted = not args.no_audio_awareness
            self.voice_wanted = not args.no_voice
            self.notifications_wanted = not args.no_notifications and os.getenv("HYPRCHAN_NOTIFICATIONS") != "off"
            self.tts_ready = False
            self.tts_id = None
            self.tts_started_at = None
            self.listen_views = {}
            self.look_requests = {}
            self.pending_audio = []
            self.audio_pending_at = 0.0
            self.reaction_interval = max(10, float(os.getenv("HYPRCHAN_REACTION_INTERVAL_SEC", "60")))
            self.pending_reaction = None
            self.last_reaction_at = -self.reaction_interval
            self.last_user_activity = 0.0
            self.user_speaking = False
            self.transcribing = False
            self.mic_wanted = not args.muted
            self.mic_active = False
            self.busy = False
            self.pending = []
            self.sequence = 0
            self.current = None
            self.response = ""
            self.stats = {"completed": 0, "mic_frames": 0, "mic_peak_dbfs": -120.0,
                          "last_timing": None, "last_error": None,
                          "reaction_checks": 0, "reactions": 0, "quiet_checks": 0,
                          "reactions_interrupted": 0, "last_reaction_timing": None}
            self.mood_values = [
                {"f": 15, "v": 0.5, "e": 0.7, "a": 0.5},
                {"f": 5, "v": 0.8, "e": 0.9, "a": 0.7},
                {"f": 95, "v": 0.1, "e": 0.1, "a": 0.1},
                {"f": 20, "v": -0.7, "e": 0.4, "a": 0.4},
            ]
            self.frames = {}
            for name, sheet in [("calm", "sit_idle"), ("sleepy", "sit_sleeping"),
                                ("grumpy", "sit_depressed")]:
                self.frames[name] = load_animation_frames(str(ROOT / f"public/assets/sprites/{sheet}.png"))
            self.frame_index = 0
            self.connect("shutdown", self.shutdown_workers)

        def do_activate(self):
            if hasattr(self, "win"):
                self.win.present()
                return
            self.win = Gtk.ApplicationWindow(application=self, title="Hyprchan · voice chat")
            self.win.set_default_size(840, 610)
            self.win.add_css_class("hyprchan-chat")
            self.win.connect("close-request", lambda *_: (self.quit(), False)[1])
            css = Gtk.CssProvider()
            css.load_from_data(b"""
                window.hyprchan-chat { background: #111d24; color: #e8f7f6; }
                .title { font-size: 25px; font-weight: 800; color: #78e0db; }
                .muted { color: #a2b8bd; font-size: 12px; }
                .message { padding: 12px; border-radius: 12px; background: #20343d; }
                .user { background: #234c50; }
                window.hyprchan-chat button, window.hyprchan-chat entry {
                    background: #243b46; color: #e8f7f6; border-color: #45616c;
                }
                window.hyprchan-chat button:hover { background: #315361; }
                window.hyprchan-chat button:checked { background: #28655f; }
                button { padding: 8px 12px; }
                entry { padding: 8px; }
                levelbar block.filled { background: #6ddcc7; }
            """)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            for side in ("top", "bottom", "start", "end"):
                getattr(outer, f"set_margin_{side}")(18)
            self.win.set_child(outer)
            title = Gtk.Label(label="Hyprchan", xalign=0)
            title.add_css_class("title")
            outer.append(title)
            self.status = Gtk.Label(label="Waking up…", xalign=0)
            self.status.set_wrap(True)
            outer.append(self.status)

            body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            body.set_vexpand(True)
            outer.append(body)
            portrait = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            self.sprite = PixelArtImage()
            self.sprite.set_size_request(175, 300)
            self.sprite.set_vexpand(True)
            portrait.append(self.sprite)
            self.mood = Gtk.DropDown.new_from_strings(["Calm", "Bright", "Sleepy", "Grumpy"])
            portrait.append(self.mood)
            body.append(portrait)
            self.scroll = Gtk.ScrolledWindow()
            self.scroll.set_hexpand(True)
            self.scroll.set_vexpand(True)
            self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.chat = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            self.scroll.set_child(self.chat)
            # Text wrapping changes the content height during GTK layout, after
            # an idle scroll may have used the previous scroll range.
            self.scroll.get_vadjustment().connect("changed", lambda *_: self.scroll_bottom())
            body.append(self.scroll)
            self.add_message("Hyprchan", "*Выглядываю из капюшона.* Секундочку, я просыпаюсь, ня~"
                             if os.getenv("HYPRCHAN_STT_LANGUAGE") == "ru" else
                             "*Peeks out of my hoodie.* Mmh… waking up, nyah~")

            microphones = json.loads(subprocess.check_output(["pactl", "-f", "json", "list", "sources"]))
            self.sources = [source for source in microphones if not source["name"].endswith(".monitor")]
            default = os.getenv("HYPRCHAN_MIC_SOURCE") or subprocess.check_output(["pactl", "get-default-source"], text=True).strip()
            devices = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.source_select = Gtk.DropDown.new_from_strings([s["description"] for s in self.sources])
            self.source_select.set_hexpand(True)
            self.source_select.set_selected(next((i for i, s in enumerate(self.sources) if s["name"] == default), 0))
            devices.append(self.source_select)
            self.language = Gtk.DropDown.new_from_strings(["Auto language", "English", "Русский"])
            self.language.set_selected({"en": 1, "ru": 2}.get(os.getenv("HYPRCHAN_STT_LANGUAGE", "en"), 0))
            devices.append(self.language)
            self.mic_button = Gtk.ToggleButton(label="Microphone on" if self.mic_wanted else "Microphone off")
            self.mic_button.set_active(self.mic_wanted)
            self.mic_button.connect("toggled", self.toggle_mic)
            devices.append(self.mic_button)
            self.source_select.connect("notify::selected", self.mic_selection_changed)
            self.language.connect("notify::selected", self.mic_selection_changed)
            outer.append(devices)
            self.level = Gtk.LevelBar.new_for_interval(0, 1)
            outer.append(self.level)
            self.mic_status = Gtk.Label(label="Preparing local speech recognition…", xalign=0)
            self.mic_status.add_css_class("muted")
            outer.append(self.mic_status)
            awareness_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            for side in ('top', 'bottom', 'start', 'end'):
                getattr(awareness_panel, 'set_margin_'+side)(12)
            awareness_popup = Gtk.Popover()
            awareness_popup.set_child(awareness_panel)
            awareness_button = Gtk.MenuButton(label='Awareness…')
            awareness_button.set_tooltip_text('Camera, screen reactions, memory, audio and notifications')
            awareness_button.set_popover(awareness_popup)
            vision = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.vision_button = Gtk.ToggleButton(label="Camera + screen on" if self.vision_wanted else "Camera + screen off")
            self.vision_button.set_active(self.vision_wanted)
            self.vision_button.connect("toggled", self.toggle_vision)
            vision.append(self.vision_button)
            self.vision_status = Gtk.Label(label="Preparing automatic visual context…", xalign=0)
            self.vision_status.set_wrap(True)
            self.vision_status.set_hexpand(True)
            self.vision_status.add_css_class("muted")
            vision.append(self.vision_status)
            awareness_panel.append(vision)
            reactions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.reaction_button = Gtk.ToggleButton(label="Screen reactions on" if self.reactions_wanted else "Screen reactions off")
            self.reaction_button.set_active(self.reactions_wanted)
            self.reaction_button.connect("toggled", self.toggle_reactions)
            reactions.append(self.reaction_button)
            self.notification_button = Gtk.ToggleButton(label="Notifications on" if self.notifications_wanted else "Notifications off")
            self.notification_button.set_active(self.notifications_wanted)
            self.notification_button.set_tooltip_text("Optional little discoveries and tangents · maximum once per 15 minutes by default")
            self.notification_button.connect("toggled", self.toggle_notifications)
            reactions.append(self.notification_button)
            reaction_note = Gtk.Label(label="About once a minute · quiet when there’s nothing new", xalign=0)
            reaction_note.add_css_class("muted")
            reactions.append(reaction_note)
            awareness_panel.append(reactions)
            memory_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.memory_button = Gtk.ToggleButton(label="Memory on" if self.memory_wanted else "Memory off")
            self.memory_button.set_active(self.memory_wanted)
            self.memory_button.connect("toggled", self.toggle_memory)
            memory_row.append(self.memory_button)
            self.memory_status = Gtk.Label(label="Learning from chats and observations · saved locally", xalign=0)
            self.memory_status.add_css_class("muted")
            memory_row.append(self.memory_status)
            awareness_panel.append(memory_row)
            audio_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.audio_button = Gtk.ToggleButton(label="Audio awareness on" if self.audio_wanted else "Audio awareness off")
            self.audio_button.set_active(self.audio_wanted)
            self.audio_button.connect("toggled", self.toggle_audio)
            audio_row.append(self.audio_button)
            self.audio_status = Gtk.Label(label="New audio channels · optional listening", xalign=0)
            self.audio_status.set_wrap(True)
            self.audio_status.add_css_class("muted")
            audio_row.append(self.audio_status)
            awareness_panel.append(audio_row)
            voice_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.voice_button = Gtk.ToggleButton(label="Voice on" if self.voice_wanted else "Voice off")
            self.voice_button.set_active(self.voice_wanted)
            self.voice_button.connect("toggled", self.toggle_voice)
            voice_row.append(self.voice_button)
            stop_voice = Gtk.Button(label="Stop speaking")
            stop_voice.connect("clicked", lambda *_: self.stop_voice())
            voice_row.append(stop_voice)
            self.voice_status = Gtk.Label(label="Warming local voices…", xalign=0)
            self.voice_status.add_css_class("muted")
            self.voice_status.set_wrap(True)
            self.voice_status.set_hexpand(True)
            voice_row.append(self.voice_status)
            voice_row.append(awareness_button)
            outer.append(voice_row)
            self.timing = Gtk.Label(label="Audio stays local · recognized text goes to the model", xalign=0)
            self.timing.add_css_class("muted")
            outer.append(self.timing)
            compose = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.entry = Gtk.Entry(placeholder_text="Or type something…")
            self.entry.set_hexpand(True)
            self.entry.connect("activate", self.submit_entry)
            self.entry.connect("changed", lambda entry: self.user_activity() if entry.get_text().strip() else None)
            compose.append(self.entry)
            send = Gtk.Button(label="Send")
            send.connect("clicked", self.submit_entry)
            compose.append(send)
            outer.append(compose)

            self.overlay = HyprchanWindow()
            self.overlay.answer_label.set_ellipsize(Pango.EllipsizeMode.END)
            self.overlay.answer_label.set_lines(6)
            self.overlay.answer_label.set_tooltip_text("Full reply in the chat window")
            self.overlay.set_application(self)
            self.overlay.set_title("hyprchan-overlay")
            self.overlay.set_default_size(230, 340)
            self.overlay.connect("close-request", lambda *_: (self.overlay.hide(), True)[1])
            from desktop_avatar import DesktopAvatar
            self.avatar = DesktopAvatar(self, portrait)
            self.overlay.present()
            self.win.present()
            GLib.timeout_add(125, self.animate)
            GLib.timeout_add(1000, self.update_vision_status)
            GLib.timeout_add(250, self.maybe_react)
            GLib.timeout_add(700, self.position_windows)
            self.start_control_socket()
            self.spawn("model", ["node", str(ROOT / "scripts/desktop_codex_bridge.mjs")])
            self.spawn("pipewire", [sys.executable, str(ROOT / "scripts/desktop_pipewire_worker.py")])
            self.spawn("tts", [os.getenv("HYPRCHAN_TTS_PYTHON", str(TTS_PYTHON) if TTS_PYTHON.exists() else sys.executable),
                               str(ROOT / "scripts/desktop_tts_worker.py")])
            if SPEECH_PYTHON.exists():
                self.spawn("speech", [str(SPEECH_PYTHON), str(ROOT / "scripts/desktop_speech_worker.py")])
                self.spawn("vision", [str(SPEECH_PYTHON), str(ROOT / "scripts/desktop_vision_worker.py")])
            else:
                self.show_error(f"Speech Python is missing: {SPEECH_PYTHON}")

        def position_windows(self):
            try:
                monitors = json.loads(subprocess.check_output(["hyprctl", "monitors", "-j"]))
                monitor = next((m for m in monitors if m.get("focused")), monitors[0])
                width = round(monitor["width"] / monitor["scale"])
                height = round(monitor["height"] / monitor["scale"])
                if monitor.get("transform", 0) % 2:
                    width, height = height, width
                left, top = monitor["x"], monitor["y"]
                reserved = monitor.get("reserved", [0, 0, 0, 0])
                left += reserved[0]
                top += reserved[1]
                width -= reserved[0] + reserved[2]
                height -= reserved[1] + reserved[3]
                clients = json.loads(subprocess.check_output(["hyprctl", "clients", "-j"]))
                for client in clients:
                    title = client.get("title", "")
                    if client.get("pid") != os.getpid():
                        continue
                    address = "address:" + client["address"]
                    if title == "hyprchan-overlay":
                        avatar_width, avatar_height = (330, 470) if self.avatar.mode == '3d' else (230, 340)
                        size = f"{avatar_width} {avatar_height}"
                        position = f"{left + max(0, width - avatar_width - 20)} {top + max(0, height - avatar_height - 30)}"
                    elif title == "Hyprchan · voice chat":
                        chat_height = min(max(720, client["size"][1]), height-24)
                        size = f"840 {chat_height}"
                        position = f"{left + max(0, (width - 840) // 2)} {top + max(0, (height - chat_height) // 2)}"
                    else:
                        continue
                    for dispatcher, value in [("setfloating", address),
                                              ("resizewindowpixel", f"exact {size},{address}"),
                                              ("movewindowpixel", f"exact {position},{address}")]:
                        subprocess.run(["hyprctl", "dispatch", dispatcher, value],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            return False

        def animate(self):
            name = ["calm", "calm", "sleepy", "grumpy"][self.mood.get_selected()]
            frames = self.frames[name]
            frame = frames[self.frame_index % len(frames)]
            self.frame_index += 1
            self.sprite.set_from_pixbuf(frame)
            self.overlay.set_image(frame)
            return not self.closing

        def add_message(self, who, text):
            label = Gtk.Label(label=f"{who}\n{text}", xalign=0)
            label.set_wrap(True)
            label.set_wrap_mode(2)
            label.set_max_width_chars(58)
            label.set_selectable(True)
            label.add_css_class("message")
            if who.startswith("You"):
                label.add_css_class("user")
            self.chat.append(label)
            GLib.idle_add(self.scroll_bottom)
            return label

        def scroll_bottom(self):
            adjustment = self.scroll.get_vadjustment()
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            return False

        def spawn(self, name, command):
            child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, bufsize=1)
            self.children[name] = child
            outgoing = self.outgoing[name] = queue.Queue(maxsize=8)
            def write_commands():
                try:
                    while True:
                        command = outgoing.get()
                        child.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
                        child.stdin.flush()
                        if command.get("type") == "quit":
                            child.stdin.close()
                            return
                except (BrokenPipeError, OSError) as exc:
                    if not self.closing:
                        GLib.idle_add(self.receive, name, {"type": "error", "fatal": True, "message": str(exc)})
            # Large image payloads must not block GTK's event loop on a pipe write.
            threading.Thread(target=write_commands, daemon=True).start()
            def read_events():
                for line in child.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    GLib.idle_add(self.receive, name, event)
                code = child.wait()
                if not self.closing:
                    GLib.idle_add(self.receive, name, {"type": "error", "fatal": True,
                                                      "message": f"{name} worker exited ({code})"})
            threading.Thread(target=read_events, daemon=True).start()

        def send(self, name, command):
            child = self.children.get(name)
            if child is None or child.poll() is not None:
                self.show_error(f"{name} worker is unavailable; reopen Hyprchan.")
                return False
            try:
                self.outgoing[name].put_nowait(command)
                return True
            except queue.Full:
                self.show_error(f"{name} worker is busy; please wait.")
                return False

        def receive(self, name, event):
            if self.closing:
                return False
            kind = event["type"]
            if kind == "error":
                self.show_error(event.get("message", "Unknown error"))
                if name == "model":
                    self.busy = False
                    self.current = None
                    if event.get("fatal"):
                        self.model_ready = False
                elif name == "vision":
                    for request_id in list(self.look_requests):
                        self.finish_look(request_id, error=event.get("message", "Visual capture failed"))
                    self.cancel_reaction()
                    self.vision_ready = False
                    self.vision_active = False
                    self.latest_visual = None
                    self.stats["vision_error"] = event.get("message", "")
                    self.update_vision_status()
                elif name == "pipewire":
                    self.stats["audio_error"] = event.get("message")
                    self.audio_status.set_label("Audio awareness unavailable: " + event.get("message", ""))
                elif name == "tts":
                    if event.get("fatal"):
                        self.tts_ready = False
                    self.tts_id = None
                    self.stats["tts_error"] = event.get("message")
                    self.voice_status.set_label("Voice unavailable: " + event.get("message", ""))
                else:
                    self.mic_status.set_label("Speech error: " + event.get("message", ""))
                return False
            if name == "model":
                if kind == "ready":
                    self.model_ready = True
                    self.stats.update(model=event["model"], tier=event["tier"], web_search=event.get("webSearch"),
                                      reasoning=event.get('reasoning'), emote_examples=event.get('emoteExamples', 0))
                    self.avatar.sync()
                    self.status.set_label("Ready · say hello or type below")
                    self.send("model", {"type": "memory_mode", "active": self.memory_wanted})
                    self.send("model", {"type": "audio_mode", "active": self.audio_wanted})
                    self.send("model", {"type": "vision_mode", "active": self.vision_wanted})
                    self.send("model", {"type": "notification_mode", "active": self.notifications_wanted})
                    self.start_next()
                elif kind == 'emote_request':
                    if self.avatar.request(event) and self.current:
                        self.current['emote_played'] = True
                elif kind == 'emote_cancelled':
                    if self.avatar.script_request == event['requestId']:
                        self.avatar.stop()
                elif kind == "notification_status":
                    if event.get("sent"):
                        self.stats["notifications_sent"] = self.stats.get("notifications_sent", 0) + 1
                    self.stats["last_notification"] = {key: event.get(key) for key in (
                        "sent", "notificationId", "reason", "cooldownSec", "retryAfterSec", "stateError")}
                elif kind == "memory":
                    self.stats["memory_active"] = event["active"]
                    self.stats["memory_count"] = event["count"]
                    self.stats["memory_error"] = event.get("error")
                    self.memory_status.set_label(event.get("error") or
                        (f"{event['count']} saved facts · chats + observations" if event["active"] else "Memory off · saved facts kept locally"))
                elif kind == "look_request":
                    self.look_requests[event["requestId"]] = event
                    self.stats["look_requests"] = self.stats.get("look_requests", 0) + 1
                    if not self.vision_wanted or not self.vision_ready:
                        self.finish_look(event["requestId"], error="Camera and screen capture are off or unavailable")
                    elif not self.send("vision", {"type": "refresh", "reason": "look", "id": event["requestId"]}):
                        self.finish_look(event["requestId"], error="Visual capture worker is unavailable")
                elif kind == "look_cancelled":
                    self.look_requests.pop(event["requestId"], None)
                elif kind == "listen_request":
                    if self.audio_wanted and self.speech_ready:
                        if not self.send("speech", {**event, "type": "listen_in"}):
                            self.receive("speech", {**event, "type": "listen_error", "message": "Speech worker is unavailable"})
                    else:
                        self.receive("speech", {**event, "type": "listen_error", "message": "Audio listening is not ready"})
                elif kind == "delta" and self.current and event["id"] == self.current["id"]:
                    self.response += event["text"]
                    self.current["first_gui_ms"] = self.current.get("first_gui_ms", (time.monotonic() - self.current["started"]) * 1000)
                    self.current["last_gui_ms"] = (time.monotonic() - self.current["started"]) * 1000
                    self.answer.set_label("Hyprchan\n" + self.response)
                    self.overlay.set_overlay_text(self.response)
                    self.speak_response(event["text"])
                    GLib.idle_add(self.scroll_bottom)
                elif kind == "done" and self.current and event["id"] == self.current["id"]:
                    if self.current["source"] in {"screen", "audio"}:
                        self.finish_reaction(event)
                        return False
                    self.response = event["text"]
                    self.answer.set_label("Hyprchan\n" + self.response)
                    self.overlay.set_overlay_text(self.response)
                    if event["status"] == "completed":
                        self.avatar.motion.react(self.response, tool_played=self.current.get('emote_played',False))
                        # Normally deltas supplied the text; retain a non-streaming fallback.
                        delta = event["text"] if not self.current["speech_phrases"].raw else ""
                        self.speak_response(delta, final=True)
                    else:
                        self.stop_voice()
                    timing = {key: event.get(key) for key in ("firstTextMs", "lastTextMs", "completedMs", "imageCount", "toolCalls", "webSearches", "tangentWords", "lookCalls", "effort", "reasoningTokens")}
                    timing.update(source=self.current["source"], sttMs=self.current.get("sttMs"),
                                  firstGuiMs=self.current.get("first_gui_ms"), lastGuiMs=self.current.get("last_gui_ms"),
                                  visualWaitMs=self.current.get("visual_wait_ms", 0))
                    if timing["lastGuiMs"] is not None:
                        timing["inputToFullTextMs"] = (self.current["started"] - self.current["received"]) * 1000 + timing["lastGuiMs"]
                    if self.current.get("endpointMs") is not None and timing["lastGuiMs"] is not None:
                        queue_ms = (self.current["started"] - self.current["received"]) * 1000
                        timing["transcriptQueueMs"] = queue_ms
                        timing["estimatedSpeechEndToTextMs"] = self.current["endpointMs"] + self.current.get("silenceMs", 0) + queue_ms + timing["lastGuiMs"]
                    self.stats["last_timing"] = timing
                    self.stats["completed"] += 1
                    full = event.get("lastTextMs")
                    label = f"Reply {full / 1000:.2f}s" if full is not None else "No reply text received"
                    if self.current.get("sttMs") is not None:
                        label = f"Speech {self.current['sttMs'] / 1000:.2f}s · " + label
                    self.timing.set_label(label)
                    self.busy = False
                    self.current = None
                    self.status.set_label("Ready · listening" if self.mic_active else "Ready")
                    if event["status"] != "completed":
                        self.show_error("; ".join(event.get("errors", [])) or event["status"])
                    self.start_next()
            elif name == "tts":
                if kind == "ready":
                    self.tts_ready = True
                    self.stats["tts_voices"] = event["voices"]
                    self.stats["tts_engine"] = event.get("engine")
                    self.stats["tts_sink"] = event["sink"]
                    self.voice_status.set_label("Local Russian + English · interrupt by speaking or typing" if self.voice_wanted else "Voice off")
                elif event.get("id") == self.tts_id:
                    if kind == 'mouth':
                        self.avatar.motion.voice(event['level'])
                    elif kind == "generated":
                        self.stats["last_tts"] = {key: event.get(key) for key in ("firstPcmMs", "synthMs", "language")}
                    elif kind == "playing":
                        self.stats.setdefault("last_tts", {}).update(firstWriteMs=event["firstWriteMs"])
                        if self.tts_started_at is not None:
                            self.stats["last_tts"]["inputToPlaybackWriteMs"] = round((time.monotonic() - self.tts_started_at) * 1000, 1)
                        self.voice_status.set_label("Speaking · tap Stop or speak to interrupt")
                    elif kind in {"done", "cancelled"}:
                        self.avatar.motion.voice(0)
                        if kind == "done":
                            self.stats.setdefault("last_tts", {}).update(
                                segments=event.get("segments"), elapsedMs=event.get("elapsedMs"))
                        self.tts_id = None
                        self.voice_status.set_label("Ready · local Russian + English" if self.voice_wanted else "Voice off")
            elif name == "pipewire":
                if kind == "ready":
                    self.stats["audio_ready"] = True
                elif kind == "audio_state":
                    self.stats["playback_streams"] = len(event["playback"])
                    self.send("model", event)
                elif kind == "audio_event":
                    self.stats["audio_events"] = self.stats.get("audio_events", 0) + 1
                    if self.audio_wanted:
                        observation = {**event, "type": "audio_event"}
                        self.pending_audio = [item for item in self.pending_audio
                                              if item.get("type") == "listen_chunk" or item.get("serial") != event["serial"]]
                        self.pending_audio.append(observation)
                        # Bound channel churn without dropping the five promised
                        # transcript chunks while a user turn is in progress.
                        latest_events = [item for item in self.pending_audio if item.get("type") != "listen_chunk"][-8:]
                        self.pending_audio = [item for item in self.pending_audio
                                              if item.get("type") == "listen_chunk" or item in latest_events]
                        self.audio_pending_at = time.monotonic()
            elif name == "vision":
                if kind == "ready":
                    self.vision_ready = True
                    self.stats["snapshot_interval_sec"] = event.get("intervalSec")
                    self.apply_vision()
                elif event.get("generation") == self.vision_generation:
                    if kind == "vision":
                        self.vision_active = event["active"]
                    elif kind == "snapshot" and self.vision_wanted:
                        self.latest_visual = event["snapshot"]
                        self.stats["camera"] = event.get("camera")
                        self.stats["capture_ms"] = event.get("captureMs")
                        self.stats["vision_error"] = event.get("cameraError")
                        for request_id in event.get("requestIds", []):
                            if request_id in self.look_requests:
                                self.finish_look(request_id, snapshot=event["snapshot"])
                        for observation in self.pending_audio:
                            if observation.get("_screen_request") in event.get("requestIds", []):
                                observation["_screen_snapshot"] = {**event["snapshot"], "images": [
                                    image for image in event["snapshot"]["images"] if image["kind"] == "screen"]}
                                observation.pop("_screen_deadline", None)
                                self.stats["heard_screen_captures"] = self.stats.get("heard_screen_captures", 0) + 1
                        if (self.reactions_wanted and event.get("reason") == "periodic" and
                                not event.get("requestIds")):
                            self.pending_reaction = event["snapshot"]
                        for item in self.pending:
                            if item["id"] in event.get("requestIds", []):
                                item["vision_waiting"] = False
                        self.start_next()
                    elif kind == "notice":
                        self.stats["vision_error"] = event["message"]
                    self.update_vision_status()
            elif kind.startswith("listen_"):
                if kind == "listen_started":
                    self.stats["listen_active"] = True
                    self.stats["listen_job"] = event["jobId"]
                    self.audio_status.set_label(f"Listening to {event['name']} · up to {event['seconds']}s")
                    self.listen_views[event["jobId"]] = {"name": event["name"], "lines": [],
                        "label": self.add_message("Heard · " + event["name"], "Listening…")}
                elif kind == "listen_chunk" and self.audio_wanted:
                    self.stats["listen_chunks"] = self.stats.get("listen_chunks", 0) + 1
                    self.stats["last_listen_chunk"] = {key: event.get(key) for key in (
                        "jobId", "index", "total", "sttMs", "model", "language", "languageMode",
                        "languageProbability", "recognitionStatus", "rejectionReason", "retryReason",
                        "attempts", "audioSeconds", "speechSeconds")}
                    self.audio_status.set_label(f"{event['name']} · heard {event['index']}/{event['total']}" if event["text"] else
                                                f"{event['name']} · no clear speech in {event['index']}/{event['total']}")
                    observation = {**event, "observedAt": time.time()}
                    self.pending_audio.append(observation)
                    if self.vision_wanted and self.vision_ready:
                        observation["_screen_request"] = f"heard-{event['jobId']}-{event['index']}"
                        observation["_screen_deadline"] = time.monotonic() + .7
                        if not self.send("vision", {"type": "refresh", "reason": "heard",
                                                    "id": observation["_screen_request"]}):
                            observation.pop("_screen_deadline", None)
                    self.audio_pending_at = 0
                    view = self.listen_views.get(event["jobId"])
                    if view:
                        view["lines"].append(transcript_line(event))
                        view["label"].set_label("Heard · " + view["name"] + "\n" + "\n".join(view["lines"]))
                        self.stats["transcript_chunks_shown"] = self.stats.get("transcript_chunks_shown", 0) + 1
                        GLib.idle_add(self.scroll_bottom)
                elif kind in {"listen_done", "listen_error"}:
                    self.stats["listen_active"] = False
                    self.send("model", {"type": "listen_finished", "jobId": event["jobId"]})
                    view = self.listen_views.pop(event["jobId"], None)
                    if view and (event.get("cancelled") or kind == "listen_error" or not view["lines"]):
                        view["lines"].append(event.get("message") or ("Listening cancelled" if event.get("cancelled") else "No clear speech recognized"))
                        view["label"].set_label("Heard · " + view["name"] + "\n" + "\n".join(view["lines"]))
                    if kind == "listen_error":
                        self.stats["listen_error"] = event["message"]
                        self.audio_status.set_label(event["message"])
                        if self.audio_wanted:
                            self.pending_audio.append({**event, "observedAt": time.time()})
                    else:
                        self.audio_status.set_label("Listening finished · watching for new audio" if self.audio_wanted else "Audio awareness off")
            elif kind == "ready":
                self.speech_ready = True
                self.stats["speech_model"] = event["model"]
                self.apply_mic()
            elif kind == "mic":
                self.mic_active = event["active"]
                if event.get("model"):
                    self.stats["speech_model"] = event["model"]
                self.mic_status.set_label("Listening · speak naturally, then pause" if self.mic_active else "Microphone off")
                if not self.mic_active:
                    self.user_speaking = False
                    self.level.set_value(0)
                    self.sprite.set_speech_glow_active(False)
                    self.overlay.set_speech_glow_active(False)
            elif kind == "level":
                self.level.set_value(max(0, min(1, (event["dbfs"] + 65) / 55)))
                self.stats["mic_frames"] = event["frames"]
                self.stats["mic_peak_dbfs"] = max(self.stats["mic_peak_dbfs"], event["dbfs"])
                self.stats["mic_dbfs"] = event["dbfs"]
                self.stats["voice_probability"] = event.get("voiceProbability")
            elif kind == "speaking":
                self.user_speaking = event["active"]
                if event["active"]:
                    self.user_activity()
                self.sprite.set_speech_glow_active(event["active"])
                self.overlay.set_speech_glow_active(event["active"])
                if event["active"] and self.vision_wanted and self.vision_ready:
                    self.send("vision", {"type": "refresh"})
            elif kind == "transcribing":
                self.transcribing = event["active"]
                if event["active"]:
                    self.user_activity()
                self.mic_status.set_label("Recognizing speech…" if event["active"] else ("Listening · speak naturally, then pause" if self.mic_active else "Microphone off"))
            elif kind == "transcript":
                if self.mic_wanted or event.get("origin") == "test_audio":
                    self.stats["last_speech_model"] = event.get("model")
                    self.stats['last_recognition_attempts'] = event.get('attempts', 1)
                    self.queue_message(event["text"], event.get("origin", "microphone"), event)
            elif kind == 'transcription_rejected':
                self.stats['rejected_transcripts'] = self.stats.get('rejected_transcripts', 0)+1
                self.stats['last_recognition_rejection'] = {key: event.get(key) for key in
                    ('rejectionReason', 'retryReason', 'attempts', 'audioSeconds', 'model')}
                self.mic_status.set_label(event['message'])
            elif kind == "notice":
                self.mic_status.set_label(event["message"])
            return False

        def show_error(self, message):
            self.stats["last_error"] = str(message)
            self.status.set_label(str(message))

        def toggle_mic(self, button):
            self.mic_wanted = button.get_active()
            button.set_label("Microphone on" if self.mic_wanted else "Microphone off")
            self.apply_mic()

        def toggle_vision(self, button):
            self.cancel_reaction()
            self.vision_wanted = button.get_active()
            button.set_label("Camera + screen on" if self.vision_wanted else "Camera + screen off")
            self.latest_visual = None
            self.apply_vision()

        def toggle_reactions(self, button):
            self.reactions_wanted = button.get_active()
            button.set_label("Screen reactions on" if self.reactions_wanted else "Screen reactions off")
            self.cancel_reaction()
            if self.reactions_wanted and self.vision_wanted and self.vision_ready:
                self.send("vision", {"type": "refresh", "reason": "periodic"})

        def toggle_memory(self, button):
            self.memory_wanted = button.get_active()
            button.set_label("Memory on" if self.memory_wanted else "Memory off")
            if self.model_ready:
                self.send("model", {"type": "memory_mode", "active": self.memory_wanted})

        def toggle_notifications(self, button):
            self.notifications_wanted = button.get_active()
            button.set_label("Notifications on" if self.notifications_wanted else "Notifications off")
            if self.model_ready:
                self.send("model", {"type": "notification_mode", "active": self.notifications_wanted})

        def toggle_audio(self, button):
            self.audio_wanted = button.get_active()
            button.set_label("Audio awareness on" if self.audio_wanted else "Audio awareness off")
            self.send("model", {"type": "audio_mode", "active": self.audio_wanted})
            if not self.audio_wanted:
                self.pending_audio = []
                self.send("speech", {"type": "stop_listening"})
                if self.current and self.current["source"] == "audio":
                    self.cancel_reaction()
            self.audio_status.set_label("New audio channels · optional listening" if self.audio_wanted else "Audio awareness off")

        def cancel_reaction(self):
            self.pending_reaction = None
            if (self.busy and self.current and self.current["source"] in {"screen", "audio"} and
                    not self.current.get("cancelled")):
                self.current["cancelled"] = True
                self.send("model", {"type": "cancel_reactions"})

        def user_activity(self):
            self.last_user_activity = time.monotonic()
            self.cancel_reaction()
            self.stop_voice()

        def toggle_voice(self, button):
            self.voice_wanted = button.get_active()
            button.set_label("Voice on" if self.voice_wanted else "Voice off")
            if not self.voice_wanted:
                self.stop_voice()
            self.voice_status.set_label("Ready · local Russian + English" if self.voice_wanted and self.tts_ready else "Voice off")

        def stop_voice(self):
            self.avatar.motion.voice(0)
            if self.current:
                self.current["voice_cancelled"] = True
            if self.tts_id is not None:
                self.send("tts", {"type": "stop"})
                self.stats["voice_interruptions"] = self.stats.get("voice_interruptions", 0) + 1
                self.tts_id = None
                self.voice_status.set_label("Speech stopped" if self.voice_wanted else "Voice off")

        def speak_response(self, delta="", final=False):
            item = self.current
            if not item or not self.tts_ready or not self.voice_wanted or item.get("voice_cancelled"):
                return
            phrases = item["speech_phrases"].feed(delta, final=final)
            if phrases and not item.get("voice_started"):
                self.tts_id = item["id"]
                self.tts_started_at = item.get("received", item["started"])
                item["voice_started"] = self.send("tts", {"type": "begin", "id": item["id"]})
            if phrases:
                # A creative tool can deliver its whole story in one delta.
                # Keep that burst in one transport slot; synthesis still streams
                # each phrase and checks cancellation between audio chunks.
                self.send("tts", {"type": "text", "id": item["id"], "phrases": phrases})
            if final and item.get("voice_started"):
                self.send("tts", {"type": "end", "id": item["id"]})

        def maybe_react(self):
            if self.closing:
                return False
            now = time.monotonic()
            if (not self.model_ready or self.busy or self.pending or self.tts_id is not None or self.user_speaking or self.transcribing or
                    self.entry.get_text().strip() or now - self.last_user_activity < 2):
                return True
            if self.audio_wanted and self.pending_audio and now - self.audio_pending_at >= 1:
                # Captions render immediately. Only model delivery briefly waits
                # for the screenshot paired with this particular heard chunk.
                if now < self.pending_audio[0].get("_screen_deadline", 0):
                    return True
                observation = self.pending_audio.pop(0)
                if time.time() - observation["observedAt"] > 60:
                    return True
                snapshot = observation.pop("_screen_snapshot", None) if self.vision_wanted else None
                observation = {key: value for key, value in observation.items() if not key.startswith("_screen_")}
                self.sequence += 1
                self.current = {"id": self.sequence, "source": "audio", "started": now,
                                "captured_at": observation["observedAt"],
                                "observation_type": observation["type"], "chunk_index": observation.get("index"),
                                "screen_captured_at": snapshot["captured_at"] if snapshot else None}
                self.busy = True
                self.status.set_label("Noticing the audio…")
                if not self.send("model", {"type": "react", "id": self.sequence,
                        "language": ["auto", "en", "ru"][self.language.get_selected()],
                        "mood": self.mood_values[self.mood.get_selected()], "observation": observation,
                        "vision": {"enabled": self.vision_wanted, "snapshot": snapshot}}):
                    self.busy = False
                    self.current = None
                return True
            if (not self.reactions_wanted or not self.vision_wanted or
                    now - self.last_reaction_at < self.reaction_interval or not self.pending_reaction):
                return True
            snapshot, self.pending_reaction = self.pending_reaction, None
            # A user conversation may have kept an observation waiting. Do not
            # volunteer a stale view; the next automatic capture will replace it.
            if time.time() - snapshot["captured_at"] > 10:
                return True
            if not any(image["kind"] == "screen" for image in snapshot["images"]):
                return True
            images = [image for image in snapshot["images"] if self.memory_wanted or image["kind"] == "screen"]
            self.sequence += 1
            self.current = {"id": self.sequence, "source": "screen", "started": now,
                            "captured_at": snapshot["captured_at"]}
            self.last_reaction_at = now
            self.busy = True
            self.status.set_label("Looking at the screen…")
            if not self.send("model", {"type": "react", "id": self.sequence,
                    "language": ["auto", "en", "ru"][self.language.get_selected()],
                    "mood": self.mood_values[self.mood.get_selected()],
                    "vision": {"enabled": True, "snapshot": {**snapshot, "images": images}}}):
                self.busy = False
                self.current = None
            return True

        def finish_reaction(self, event):
            self.stats["last_reaction_timing"] = {
                key: event.get(key) for key in ("firstTextMs", "lastTextMs", "completedMs", "imageCount", "status", "quiet", "toolCalls", "webSearches", "tangentWords")}
            self.stats["last_reaction_timing"].update(
                capturedAt=self.current["captured_at"],
                elapsedMs=round((time.monotonic() - self.current["started"]) * 1000, 1))
            if self.current.get("observation_type") == "listen_chunk":
                self.stats["heard_chunks_processed"] = self.stats.get("heard_chunks_processed", 0) + 1
                self.stats["heard_chunks_with_screen"] = self.stats.get("heard_chunks_with_screen", 0) + event.get("imageCount", 0)
                self.stats["last_heard_timing"] = {**self.stats["last_reaction_timing"],
                    "index": self.current["chunk_index"], "screenCapturedAt": self.current["screen_captured_at"]}
            error = None
            if event["status"] == "completed" and not self.current.get("cancelled"):
                self.stats["reaction_checks"] += 1
                if event.get("quiet"):
                    self.stats["quiet_checks"] += 1
                elif event.get("text", "").strip() and (
                        (self.current["source"] == "audio" and self.audio_wanted) or
                        (self.current["source"] == "screen" and self.reactions_wanted and self.vision_wanted)):
                    self.add_message("Hyprchan", event["text"])
                    self.overlay.set_overlay_text(event["text"])
                    self.avatar.motion.react(event['text'], tool_played=self.current.get('emote_played',False))
                    self.current["speech_phrases"] = SpeechPhrases()
                    self.speak_response(event["text"], final=True)
                    self.stats["reactions"] += 1
            elif event["status"] == "interrupted" or self.current.get("cancelled"):
                self.stats["reactions_interrupted"] += 1
            else:
                error = "; ".join(event.get("errors", [])) or event["status"]
            self.current = None
            self.busy = False
            self.status.set_label("Ready · listening" if self.mic_active else "Ready")
            if error:
                self.show_error(error)
            self.start_next()

        def finish_look(self, request_id, snapshot=None, error=None):
            request = self.look_requests.pop(request_id, None)
            if request is None:
                return
            if not self.vision_wanted:
                error = "Camera and screen capture are off"
            result = {"type": "look_result", "requestId": request_id}
            if error:
                result["error"] = error
            else:
                source = request["source"]
                wanted = {"screen", "webcam"} if source == "both" else {"webcam" if source == "camera" else "screen"}
                images = [image for image in snapshot["images"] if image["kind"] in wanted]
                result["snapshot"] = {**snapshot, "images": images}
                self.stats["look_captures"] = self.stats.get("look_captures", 0) + 1
                self.stats["last_look"] = {"source": source, "capturedAt": snapshot["captured_at"],
                                           "images": [image["kind"] for image in images]}
            self.send("model", result)

        def apply_vision(self):
            if self.model_ready:
                self.send("model", {"type": "vision_mode", "active": self.vision_wanted})
            if not self.vision_wanted:
                for request_id in list(self.look_requests):
                    self.finish_look(request_id, error="Camera and screen capture are off")
                for observation in self.pending_audio:
                    for key in list(observation):
                        if key.startswith("_screen_"):
                            observation.pop(key)
            self.vision_generation += 1
            self.stats["vision_error"] = None
            if self.vision_ready:
                self.send("vision", {"type": "enable", "active": self.vision_wanted,
                                     "generation": self.vision_generation})
            self.update_vision_status()

        def update_vision_status(self):
            if not self.vision_wanted:
                text = "Capture off · earlier images remain in this chat"
            elif self.latest_visual:
                kinds = [image["kind"] for image in self.latest_visual["images"]]
                sources = "Camera + screen" if len(kinds) == 2 else ("Camera" if "webcam" in kinds else "Screen only")
                age = max(0, int(time.time() - self.latest_visual["captured_at"]))
                delivery = "automatic screen reactions" if self.reactions_wanted else "images sent with chat"
                text = f"{sources} · {age}s ago · {delivery}"
                if self.stats.get("vision_error"):
                    text += " · camera unavailable; retrying"
            else:
                text = self.stats.get("vision_error") or "Preparing automatic visual context…"
            self.vision_status.set_label(text)
            return not self.closing

        def mic_selection_changed(self, *_):
            self.apply_mic()

        def apply_mic(self):
            if not self.speech_ready:
                return
            if self.mic_wanted and self.sources:
                self.send("speech", {"type": "listen", "source": self.sources[self.source_select.get_selected()]["name"],
                                     "language": [None, "en", "ru"][self.language.get_selected()]})
                self.mic_status.set_label("Opening microphone…")
            else:
                self.send("speech", {"type": "mute"})

        def submit_entry(self, *_):
            text = self.entry.get_text().strip()
            if text:
                self.queue_message(text, "keyboard")
                self.entry.set_text("")

        def queue_message(self, text, source, metadata=None):
            self.user_activity()
            if len(self.pending) >= 3:
                self.show_error("Please wait for the queued messages to finish.")
                return
            self.sequence += 1
            item = {"id": self.sequence, "text": text[:8000], "source": source,
                    "received": time.monotonic(), **(metadata or {})}
            self.pending.append(item)
            self.add_message("You · voice" if source != "keyboard" else "You", text)
            self.start_next()

        def start_next(self):
            if not self.model_ready or self.busy or not self.pending:
                return
            item = self.pending[0]
            if item.get("vision_waiting"):
                return
            if (self.vision_wanted and self.vision_ready and not item.get("vision_requested") and
                    (not self.latest_visual or time.time() - self.latest_visual["captured_at"] > 2)):
                item["vision_requested"] = time.monotonic()
                item["vision_waiting"] = self.send("vision", {"type": "refresh", "id": item["id"]})
                if item["vision_waiting"]:
                    GLib.timeout_add(700, self.finish_visual_wait, item["id"])
                    return
            self.current = self.pending.pop(0)
            if self.current.get("vision_requested"):
                self.current["visual_wait_ms"] = (time.monotonic() - self.current["vision_requested"]) * 1000
            self.current["started"] = time.monotonic()
            self.current["speech_phrases"] = SpeechPhrases()
            self.response = ""
            self.answer = self.add_message("Hyprchan", "…")
            self.busy = True
            self.status.set_label("Replying…")
            if not self.send("model", {"type": "chat", "id": self.current["id"], "text": self.current["text"],
                                       "mood": self.mood_values[self.mood.get_selected()],
                                       "vision": {"enabled": self.vision_wanted,
                                                  "snapshot": self.latest_visual if self.vision_wanted else None}}):
                self.busy = False

        def finish_visual_wait(self, item_id):
            for item in self.pending:
                if item["id"] == item_id:
                    item["vision_waiting"] = False
            self.start_next()
            return False

        def start_control_socket(self):
            SOCKET.unlink(missing_ok=True)
            self.server = socket.socket(socket.AF_UNIX)
            self.server.bind(str(SOCKET))
            os.chmod(SOCKET, 0o600)
            self.server.listen(3)
            self.server.settimeout(1)
            def serve():
                while not self.closing:
                    try:
                        client, _ = self.server.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    with client:
                        try:
                            client.settimeout(3)
                            command = json.loads(client.makefile().readline(16384))
                            result = queue.Queue(maxsize=1)
                            GLib.idle_add(self.handle_control, command, result)
                            client.sendall((json.dumps(result.get(timeout=3)) + "\n").encode())
                        except (OSError, ValueError, queue.Empty):
                            pass
            threading.Thread(target=serve, daemon=True).start()

        def handle_control(self, command, result):
            try:
                kind = command.get("type")
                if kind == "chat":
                    self.entry.set_text(command["text"])
                    self.submit_entry()
                elif kind == "mic":
                    self.mic_button.set_active(bool(command["active"]))
                elif kind == "vision":
                    self.vision_button.set_active(bool(command["active"]))
                elif kind == "reactions":
                    self.reaction_button.set_active(bool(command["active"]))
                elif kind == "memory":
                    self.memory_button.set_active(bool(command["active"]))
                elif kind == "audio":
                    self.audio_button.set_active(bool(command["active"]))
                elif kind == "voice":
                    self.voice_button.set_active(bool(command["active"]))
                elif kind == "notifications":
                    self.notification_button.set_active(bool(command["active"]))
                elif kind == "stop_voice":
                    self.stop_voice()
                elif kind == 'avatar':
                    self.avatar.set_mode(command['mode'])
                elif kind == 'emote':
                    self.avatar.play(command['id'], command.get('seconds', 6))
                elif kind == 'emote_stop':
                    self.avatar.stop()
                elif kind == 'avatar_capture':
                    if not self.avatar.widgets: raise ValueError('Select 3D first')
                    self.avatar.widgets[-1].capture(command['path'])
                elif kind == "snapshot":
                    self.send("vision", {"type": "refresh", "reason": "periodic"})
                elif kind == "test_audio":
                    self.send("speech", {"type": "transcribe_file", "path": command["path"],
                                         "language": command.get("language")})
                elif kind == "language":
                    self.language.set_selected({"auto": 0, "en": 1, "ru": 2}[command["language"]])
                elif kind == "present":
                    self.win.present()
                    self.overlay.present()
                elif kind == "quit":
                    GLib.timeout_add(100, lambda: (self.quit(), False)[1])
                elif kind != "status":
                    raise ValueError("Unknown control command")
                result.put({"pid": os.getpid(), "ready": self.model_ready, "speech_ready": self.speech_ready,
                            "microphone": self.sources[self.source_select.get_selected()]["description"] if self.sources else None,
                            "language": ["auto", "en", "ru"][self.language.get_selected()],
                            "vision_active": self.vision_active, "vision_wanted": self.vision_wanted,
                            "reactions_active": self.reactions_wanted,
                            "memory_wanted": self.memory_wanted, "audio_active": self.audio_wanted,
                            "voice_active": self.voice_wanted, "tts_ready": self.tts_ready,
                            "notifications_active": self.notifications_wanted,
                            'avatar': self.avatar.status(), 'mic_wanted': self.mic_wanted,
                            "tts_playing": self.tts_id is not None,
                            "audio_pending": len(self.pending_audio),
                            "reaction_interval_sec": self.reaction_interval,
                            "reaction_pending": self.pending_reaction is not None,
                            "busy_kind": self.current["source"] if self.busy and self.current else None,
                            "visual_sources": [image["kind"] for image in self.latest_visual["images"]] if self.latest_visual else [],
                            "visual_age_sec": round(time.time() - self.latest_visual["captured_at"], 1) if self.latest_visual else None,
                            "mic_active": self.mic_active, "busy": self.busy, "queued": len(self.pending), **self.stats})
            except Exception as exc:
                result.put({"error": str(exc)})
            return False

        def shutdown_workers(self, *_):
            self.closing = True
            if hasattr(self, 'avatar'): self.avatar.close()
            if hasattr(self, "server"):
                self.server.close()
            SOCKET.unlink(missing_ok=True)
            for name, child in self.children.items():
                if child.poll() is None:
                    try:
                        self.outgoing[name].put_nowait({"type": "quit"})
                    except queue.Full:
                        pass
            for child in self.children.values():
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()

    app = Desktop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (app.quit(), False)[1])
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
