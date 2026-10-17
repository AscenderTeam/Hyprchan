"""Turn streamed companion text into bounded spoken phrases (no audio I/O)."""
import json
import os
from pathlib import Path
import re
import subprocess


def voice_settings_path():
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home()/".config")))/"hyprchan/voice.json"


def voice_enabled():
    path = voice_settings_path()
    if not path.exists():
        return True
    try:
        return json.loads(path.read_text()).get("enabled") is True
    except (OSError, ValueError, AttributeError):
        return False


def save_voice_enabled(enabled):
    path = voice_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump({"enabled": bool(enabled)}, stream)
        stream.write("\n")
    temporary.replace(path)


def playback_target(requested=None):
    """Resolve just before playback, and lock to this exact PipeWire node.

    A missing explicit target is an error, never an invitation to use speakers.
    The serial prevents a removed device's replacement from inheriting a stream.
    """
    if not requested:
        requested = subprocess.check_output(["pactl", "get-default-sink"], text=True, timeout=3).strip()
    sinks = json.loads(subprocess.check_output(["pactl", "-f", "json", "list", "sinks"],
                                              text=True, timeout=3))
    for sink in sinks:
        serial = str(sink.get("properties", {}).get("object.serial", ""))
        if requested in {sink["name"], serial} and serial.isdigit():
            return sink["name"], serial, sink.get("description", sink["name"])
    raise RuntimeError("Selected voice output is unavailable. Speech stays silent.")


def playback_properties():
    return {"application.name": "Hyprchan voice", "node.name": "hyprchan-voice",
            "media.name": "Hyprchan speech", "node.dont-reconnect": True,
            "node.dont-fallback": True, "node.dont-move": True}


def spoken_text(text):
    # Incomplete action/code spans are withheld until their closing delimiter.
    text = re.sub(r"```.*?(?:```|$)", " ", text, flags=re.S)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*[^*]*(?:\*|$)", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[`#_~]", "", text)
    text = re.sub(r"[^\w\s.,!?;:'’\"«»()—–\-…]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class SpeechPhrases:
    """Flush at sentence boundaries, then clauses/word limits for long sentences."""
    def __init__(self):
        self.raw = ""
        self.consumed = 0

    def feed(self, delta="", final=False):
        self.raw += delta
        if self.raw.strip().upper() == "NO_REPLY":
            return []
        clean = spoken_text(self.raw)
        output = []
        while self.consumed < len(clean):
            remaining = clean[self.consumed:].lstrip()
            skipped = len(clean[self.consumed:]) - len(remaining)
            boundary = re.search(r"(?<!\d)[.!?…]+[\"»’)]*(?=\s|$)", remaining)
            end = boundary.end() if boundary else None
            if end is not None and end > 150:
                end = None
            if end is None and len(remaining) >= 90:
                clause = re.search(r"[,;:](?=\s)", remaining[24:120])
                if clause:
                    end = 24 + clause.end()
            if end is None and len(remaining) >= 150:
                end = remaining.rfind(" ", 40, 140)
                if end < 0:
                    end = 140
            if end is None and final:
                end = len(remaining)
            if end is None:
                break
            phrase = remaining[:end].strip()
            self.consumed += skipped + end
            if re.search(r"\w", phrase):
                output.append(phrase)
        return output


def speech_language(text):
    return "ru" if re.search(r"[А-Яа-яЁё]", text) else "en"


def transcript_line(event):
    text = event.get("text", "").strip()
    language = f" {event['language'].upper()} ·" if text and event.get("language") else ""
    if not text:
        text = ("Unclear audio — could not transcribe reliably" if event.get("recognitionStatus") == "unclear"
                else "No clear speech recognized")
    return f"[{event['index']}/{event['total']}]{language} {text}"
