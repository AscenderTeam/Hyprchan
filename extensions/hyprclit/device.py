from __future__ import annotations

import math
import os
import select
import struct

EV_SYN = 0x00
EV_REL = 0x02
SYN_REPORT = 0
REL_X = 0
REL_Y = 1


class EvdevRelativeReader:
    EVENT_STRUCT = struct.Struct("llHHi")

    def __init__(self) -> None:
        self._buf = bytearray()
        self._dx = 0
        self._dy = 0

    def read_magnitudes(self, fd: int) -> list[float]:
        magnitudes: list[float] = []
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                break
            if not data:
                raise OSError("input event stream closed")

            self._buf.extend(data)
            usable = len(self._buf) - (len(self._buf) % self.EVENT_STRUCT.size)
            offset = 0

            while offset < usable:
                _sec, _usec, event_type, code, value = self.EVENT_STRUCT.unpack_from(
                    self._buf, offset
                )
                offset += self.EVENT_STRUCT.size

                if event_type == EV_REL:
                    if code == REL_X:
                        self._dx += value
                    elif code == REL_Y:
                        self._dy += value
                elif event_type == EV_SYN and code == SYN_REPORT:
                    if self._dx or self._dy:
                        magnitudes.append(math.hypot(self._dx, self._dy))
                    self._dx = 0
                    self._dy = 0

            if usable:
                del self._buf[:usable]

        return magnitudes


def detect_trackpoint_event_device() -> str | None:
    sys_class = "/sys/class/input"
    try:
        entries = sorted(
            name for name in os.listdir(sys_class) if name.startswith("event")
        )
    except OSError:
        return None

    for event_name in entries:
        name_path = os.path.join(sys_class, event_name, "device", "name")
        try:
            with open(name_path, "r", encoding="utf-8", errors="replace") as file:
                device_name = file.read().strip()
        except OSError:
            continue

        if "trackpoint" in device_name.lower():
            return os.path.join("/dev/input", event_name)
    return None
