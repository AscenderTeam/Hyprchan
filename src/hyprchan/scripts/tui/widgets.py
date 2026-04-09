from __future__ import annotations

import time

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from hyprchan.scripts.tui.api import ServerSnapshot


class GlowHeader(Static):
    def __init__(self) -> None:
        super().__init__()
        self._pulse = 0

    def pulse(self, connected: bool) -> None:
        dots = "." * (self._pulse % 4)
        status = "ONLINE" if connected else "OFFLINE"
        color = "#7ef9a3" if connected else "#ff7b7b"
        text = Text.from_markup(
            f"[b]HYPRCHAN[/b]  [dim]tui[/dim]  [bold {color}]{status}[/bold {color}] {dots}"
        )
        self.update(text)
        self._pulse += 1


class MessageBubble(Static):
    def __init__(self, role: str, content: str, timestamp: float | None = None) -> None:
        super().__init__()
        self.role = role
        self.content = content
        self.timestamp = timestamp or time.time()
        self.add_class("bubble", f"role-{role}")

    def render(self) -> Text:
        stamp = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        tag = {
            "user": "YOU",
            "assistant": "HYPR",
            "system": "SYS",
            "tool": "TOOL",
        }.get(self.role, self.role.upper())
        header = Text(f"{tag}  {stamp}\n", style="bold #9fb3c8")
        body = Text(self.content, style="#e6edf3")
        return header + body


class ChatLog(VerticalScroll):
    def __init__(self) -> None:
        super().__init__(id="chat-log")
        self._follow = True

    def set_follow(self, follow: bool) -> None:
        self._follow = follow

    async def add_message(self, role: str, content: str, timestamp: float | None = None) -> None:
        await self.mount(MessageBubble(role, content, timestamp))
        if self._follow:
            self.scroll_end(animate=False)


class StatusPanel(Static):
    def __init__(self) -> None:
        super().__init__(id="status-panel")
        self.snapshot = ServerSnapshot()

    def update_snapshot(self, snapshot: ServerSnapshot) -> None:
        self.snapshot = snapshot
        self.refresh()

    def render(self) -> Text:
        snap = self.snapshot
        color = "#7ef9a3" if snap.connected else "#ff7b7b"
        text = Text()
        text.append("SERVER\n", style="bold #9fb3c8")
        text.append("Status: ", style="#8aa4bf")
        text.append("online\n" if snap.connected else "offline\n", style=color)
        text.append(f"Phase: {snap.phase}\n", style="#8aa4bf")
        text.append(f"Reason: {snap.active_reason}\n", style="#8aa4bf")
        text.append(f"Next ponder: {snap.next_ponder_sec:.1f}s\n", style="#8aa4bf")
        text.append(f"Latest event: {snap.latest_event_id}\n", style="#8aa4bf")
        if snap.memory_gate:
            mem = snap.memory_gate
            text.append("\nMEMORY\n", style="bold #9fb3c8")
            text.append(f"Enabled: {mem.get('enabled')}\n", style="#8aa4bf")
            text.append(
                f"Sleep: {mem.get('sleep_enabled')}\n",
                style="#8aa4bf",
            )
            text.append(
                f"Ready: {mem.get('service_ready')}\n",
                style="#8aa4bf",
            )
        if snap.last_error:
            text.append("\nLAST ERROR\n", style="bold #f5a96c")
            text.append(str(snap.last_error)[:240], style="#f5c0a1")
        return text


class SystemLog(VerticalScroll):
    def __init__(self) -> None:
        super().__init__(id="system-log")

    async def add_line(self, text: str) -> None:
        await self.mount(Static(text, classes="system-line"))
        self.scroll_end(animate=False)
