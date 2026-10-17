"""Persistent executable emotes. Full user permissions, isolated GUI lifecycle."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

from .motion import BUILTINS, validate_frame

EMOTE_DIRECTORY = Path(os.getenv('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'hyprchan-codex/emotes'


class EmoteLibrary:
    def __init__(self, directory=EMOTE_DIRECTORY):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)

    def path(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', identity):
            raise ValueError('Use an emote id of 1–48 lowercase letters, numbers, or underscores')
        return self.directory / f'{identity}.py'

    def save(self, identity, title, description, code):
        path = self.path(identity)
        if identity in BUILTINS: raise ValueError('Choose a new id; built-in emotes are kept intact')
        if not isinstance(code, str) or not 1 <= len(code.encode()) <= 24_000:
            raise ValueError('Python source must be 1–24000 bytes')
        if not isinstance(title, str) or not 1 <= len(title) <= 80:
            raise ValueError('Give the emote a short title')
        if not isinstance(description, str) or len(description) > 300:
            raise ValueError('Description is limited to 300 characters')
        compile(code, str(path), 'exec')
        metadata = {'id': identity, 'title': title, 'description': description, 'updatedAt': time.time()}
        for target, content in [(path, code), (path.with_suffix('.json'), json.dumps(metadata, ensure_ascii=False))]:
            temporary = target.with_suffix(target.suffix + '.tmp')
            # Replace a file atomically; never follow a preexisting script symlink.
            temporary.unlink(missing_ok=True)
            with temporary.open('x', encoding='utf-8') as stream:
                os.chmod(temporary, 0o600)
                stream.write(content)
            temporary.replace(target)
        return metadata

    def list(self):
        result = [{'id': key, 'title': item[0], 'builtin': True} for key, item in BUILTINS.items()]
        for path in sorted(self.directory.glob('*.json')):
            try:
                if path.stat().st_size > 4096: continue
                item = json.loads(path.read_text())
                script = self.path(item['id'])
                if script.is_file() and item['id'] not in BUILTINS:
                    result.append({'id': item['id'], 'title': str(item['title'])[:80], 'builtin': False,
                                   'description': str(item.get('description', ''))[:300]})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return result


class EmoteRunner:
    """Last-frame mailbox avoids queuing script output onto GTK's event loop."""
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.latest = None
        self.event = None
        self.identity = None

    @staticmethod
    def terminate(process):
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: return
        try: process.wait(timeout=.3)
        except subprocess.TimeoutExpired: pass
        # Also reap descendants left behind by a script whose parent exited.
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        try: process.wait(timeout=1)
        except subprocess.TimeoutExpired: pass

    def stop(self):
        with self.lock:
            process = self.process
            self.process = None
            self.identity = None
            self.latest = None
            self.event = {'state': 'stopped'}
        if process:
            threading.Thread(target=self.terminate, args=(process,), daemon=True).start()

    def play(self, path, seconds=12):
        self.stop()
        seconds = float(seconds)
        if not 1 <= seconds <= 30: raise ValueError('Script run limit must be 1–30 seconds')
        path = Path(path).resolve(strict=True)
        if path.stat().st_size > 24_000: raise ValueError('Emote source exceeds 24000 bytes')
        compile(path.read_text(), str(path), 'exec')
        source = str(Path(__file__).resolve().parents[4])
        env = {**os.environ, 'PYTHONPATH': source + os.pathsep + os.environ.get('PYTHONPATH', '')}
        process = subprocess.Popen([sys.executable, '-u', str(path)], cwd=path.parent, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        with self.lock:
            self.process = process
            self.identity = path.stem
            self.event = {'state': 'playing', 'id': path.stem}
        threading.Thread(target=self.read, args=(process, path.stem, seconds), daemon=True).start()
        return {'started': True, 'id': path.stem, 'maxSeconds': seconds}

    def read(self, process, identity, seconds):
        errors = bytearray()
        timed_out = threading.Event()
        def drain_errors():
            with process.stderr:
                while data := process.stderr.read(1024):
                    errors.extend(data)
                    del errors[:-2048]
        def deadline():
            timed_out.set()
            self.terminate(process)
        threading.Thread(target=drain_errors, daemon=True).start()
        timer = threading.Timer(seconds, deadline); timer.daemon = True; timer.start()
        error = None
        frames = 0
        try:
            while line := process.stdout.readline(16385):
                if len(line) > 16384: raise ValueError('Emote frame exceeds 16 KiB')
                pose = validate_frame(json.loads(line))
                frames += 1
                with self.lock:
                    if self.process is not process: break
                    self.latest = pose
            process.wait(timeout=1)
            if process.returncode and not timed_out.is_set():
                error = errors.decode(errors='replace').strip()[-1000:] or f'Emote exited ({process.returncode})'
            if not frames and not error: error = 'Emote produced no animation frames'
        except Exception as exc:
            error = str(exc)
        finally:
            timer.cancel()
            self.terminate(process)
            process.stdout.close()
            with self.lock:
                if self.process is process:
                    self.process = None
                    self.identity = None
                    self.event = {'state': 'error' if error else 'finished', 'id': identity,
                                  'frames': frames, 'error': error, 'timedOut': timed_out.is_set()}

    def poll(self):
        with self.lock:
            frame, event = self.latest, self.event
            self.latest = self.event = None
        return frame, event
