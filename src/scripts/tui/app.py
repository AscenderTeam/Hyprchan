from __future__ import annotations

import logging
import os
import time
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, TextArea

from scripts.tui.api import HyprApiClient, ServerSnapshot
from scripts.tui.widgets import ChatLog, GlowHeader, StatusPanel, SystemLog


class HyprTUI(App):
    CSS = """
    Screen {
        background: #0a0f14;
        color: #e6edf3;
    }

    #app-root {
        height: 100%;
        width: 100%;
    }

    #main-row {
        height: 1fr;
    }

    #chat-log {
        background: #0f1620;
        border: round #1f2a36;
        padding: 1 2;
    }

    #sidebar {
        width: 32;
        background: #0d131b;
        border: round #1f2a36;
        padding: 1 2;
    }

    #status-panel {
        height: 1fr;
    }

    #system-log {
        height: 1fr;
        border-top: solid #1f2a36;
        padding-top: 1;
    }

    #input-panel {
        height: 7;
        background: #0d131b;
        border: round #1f2a36;
        padding: 0 1;
    }

    #input {
        height: 5;
        border: round #2b3a4a;
        background: #0a0f14;
        padding: 0 1;
    }

    .bubble {
        margin: 0 0 1 0;
        padding: 1 2;
        border: round #2a3645;
        background: #101825;
    }

    .role-user {
        border: round #2b5b7c;
        background: #0f2233;
    }

    .role-assistant {
        border: round #4b2b5e;
        background: #1a1426;
    }

    .role-system {
        border: round #3a3f52;
        background: #151a23;
    }

    .system-line {
        color: #8aa4bf;
        padding: 0 1 0 0;
    }
    """

    BINDINGS = [
        ("ctrl+enter", "send", "Send"),
        ("ctrl+f", "toggle_follow", "Follow"),
        ("ctrl+l", "clear", "Clear"),
        ("ctrl+r", "reconnect", "Reconnect"),
        ("ctrl+q", "quit", "Quit"),
    ]

    mode = reactive("INSERT")

    def __init__(self, *, api_url: str, poll_interval: float = 1.0) -> None:
        super().__init__()
        self.api_url = api_url.rstrip("/")
        self.poll_interval = poll_interval
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        self.api = HyprApiClient(self.api_url)
        self.snapshot = ServerSnapshot()
        self._seen_event_ids: set[int] = set()
        self._last_event_id = 0
        self._caret_visible = True

    def compose(self) -> ComposeResult:
        with Container(id="app-root"):
            yield Header(show_clock=True)
            yield GlowHeader()
            with Horizontal(id="main-row"):
                yield ChatLog()
                with Vertical(id="sidebar"):
                    yield StatusPanel()
                    yield SystemLog()
            with Container(id="input-panel"):
                yield TextArea(
                    id="input",
                    text="Type here... /help for commands - Ctrl+Enter to send",
                )
            yield Footer()

    async def on_mount(self) -> None:
        self.query_one(TextArea).focus()
        self.set_interval(0.5, self._pulse)
        self.set_interval(self.poll_interval, self._poll_server)
        await self._log_system("Booting TUI... waiting for daemon API")

    async def on_unmount(self) -> None:
        await self.api.close()

    async def _log_system(self, text: str) -> None:
        await self.query_one(SystemLog).add_line(text)

    async def _pulse(self) -> None:
        self.query_one(GlowHeader).pulse(self.snapshot.connected)

    def _set_snapshot(self, data: dict[str, Any], *, connected: bool) -> None:
        self.snapshot = ServerSnapshot(
            connected=connected,
            phase=str(data.get("phase", "-")),
            active_reason=str(data.get("active_reason", "-")),
            next_ponder_sec=float(data.get("next_passive_ponder_sec", 0.0) or 0.0),
            latest_event_id=int(data.get("latest_event_id", 0) or 0),
            memory_gate=data.get("memory_gate"),
            last_error=data.get("last_inference_error"),
        )
        self.query_one(StatusPanel).update_snapshot(self.snapshot)

    async def _poll_server(self) -> None:
        try:
            data = await self.api.fetch_events(since_id=self._last_event_id)
        except Exception as exc:
            if self.snapshot.connected:
                await self._log_system(f"Disconnected: {exc}")
            self.snapshot.connected = False
            self.query_one(StatusPanel).update_snapshot(self.snapshot)
            return

        self._set_snapshot(data, connected=True)
        latest = int(data.get("latest_event_id", 0) or 0)
        self._last_event_id = max(self._last_event_id, latest)

        events = data.get("events", [])
        if isinstance(events, list):
            for item in events:
                await self._handle_event(item)

    async def _handle_event(self, item: dict[str, Any]) -> None:
        event_id = int(item.get("id", 0) or 0)
        if event_id in self._seen_event_ids:
            return
        self._seen_event_ids.add(event_id)

        event_type = str(item.get("type", ""))
        origin = str(item.get("origin", ""))
        is_user = bool(item.get("is_user", False))
        description = str(item.get("description", "")).strip()
        timestamp = float(item.get("timestamp", time.time()) or time.time())

        if event_type == "communication_message" and is_user:
            await self.query_one(ChatLog).add_message("user", description, timestamp)
        elif event_type == "agent_response" or origin == "hyprchan_agent":
            await self.query_one(ChatLog).add_message(
                "assistant", description, timestamp
            )
        elif event_type in {"context_compaction", "tool_observation"}:
            await self.query_one(ChatLog).add_message("system", description, timestamp)
        else:
            short = description or f"{event_type} ({origin})"
            if short:
                await self._log_system(short)

    async def action_send(self) -> None:
        input_box = self.query_one(TextArea)
        content = input_box.text.strip()
        if not content:
            return
        input_box.text = ""
        if content.startswith("/") or content.startswith(":"):
            await self._handle_command(content)
            return

        if not self.snapshot.connected:
            await self._log_system("Daemon offline; message queued locally only.")
            await self.query_one(ChatLog).add_message("user", content)
            return

        try:
            response = await self.api.send_message(content)
        except Exception as exc:
            await self._log_system(f"Send failed: {exc}")
            await self.query_one(ChatLog).add_message("user", content)
            return

        event_id = int(response.get("event_id", 0) or 0)
        if event_id:
            self._seen_event_ids.add(event_id)
        await self.query_one(ChatLog).add_message("user", content)

        if response.get("status") == "pending":
            await self._log_system("Agent response pending...")

    async def _handle_command(self, raw: str) -> None:
        text = raw.lstrip("/: ").strip()
        if not text:
            return
        parts = text.split()
        command = parts[0].lower()
        args = parts[1:]

        if command in {"quit", "exit", "q"}:
            await self.action_quit()
            return
        if command in {"clear", "cls"}:
            await self.action_clear()
            return
        if command in {"follow", "f"}:
            await self.action_toggle_follow()
            return
        if command in {"summon"}:
            await self._summon()
            return
        if command in {"server", "connect"}:
            if not args:
                await self._log_system("Usage: /server http://localhost:8000/v1")
                return
            await self._repoint_api(args[0])
            return
        if command in {"help", "?"}:
            await self._log_system(
                "Commands: /help /quit /clear /follow /summon /server <url>"
            )
            return

        await self._log_system(f"Unknown command: {command}")

    async def _summon(self) -> None:
        if not self.snapshot.connected:
            await self._log_system("Daemon offline; cannot summon.")
            return
        try:
            payload = await self.api.summon()
        except Exception as exc:
            await self._log_system(f"Summon failed: {exc}")
            return
        phase = payload.get("phase", "-")
        await self._log_system(f"Summon ok. Phase: {phase}")

    async def _repoint_api(self, url: str) -> None:
        await self.api.close()
        self.api_url = url.rstrip("/")
        self.api = HyprApiClient(self.api_url)
        self.snapshot.connected = False
        self.query_one(StatusPanel).update_snapshot(self.snapshot)
        await self._log_system(f"Repointed API to {self.api_url}")

    async def action_toggle_follow(self) -> None:
        chat = self.query_one(ChatLog)
        chat.set_follow(not chat._follow)
        state = "on" if chat._follow else "off"
        await self._log_system(f"Auto-follow {state}")

    async def action_clear(self) -> None:
        chat = self.query_one(ChatLog)
        await chat.remove_children()
        await self._log_system("Chat cleared")

    async def action_reconnect(self) -> None:
        await self._log_system("Reconnecting...")
        await self._poll_server()

    async def on_key(self, event) -> None:
        if self.mode == "NORMAL":
            key = event.key
            chat = self.query_one(ChatLog)
            if key == "j":
                chat.scroll_down(animate=False)
                event.stop()
            elif key == "k":
                chat.scroll_up(animate=False)
                event.stop()
            elif key == "g":
                chat.scroll_home(animate=False)
                event.stop()
            elif key == "G":
                chat.scroll_end(animate=False)
                event.stop()
            elif key == "i":
                self._set_insert_mode()
                await self._log_system("Mode: INSERT")
                event.stop()
        elif event.key == "escape":
            self._set_normal_mode()
            await self._log_system("Mode: NORMAL")

    def _set_caret_visible(self, visible: bool) -> None:
        if self._caret_visible == visible:
            return
        input_box = self.query_one(TextArea)
        input_box.styles.caret_color = "#e6edf3" if visible else "transparent"
        if hasattr(input_box, "cursor_blink"):
            input_box.cursor_blink = visible
        if hasattr(input_box, "show_cursor"):
            input_box.show_cursor = visible
        self._caret_visible = visible

    def _set_insert_mode(self) -> None:
        self.mode = "INSERT"
        input_box = self.query_one(TextArea)
        input_box.focus()
        self._set_caret_visible(True)

    def _set_normal_mode(self) -> None:
        self.mode = "NORMAL"
        input_box = self.query_one(TextArea)
        input_box.blur()
        self._set_caret_visible(False)


def _read_poll_interval() -> float:
    raw = os.getenv("HYPRCHAN_TUI_POLL_INTERVAL", "").strip()
    if not raw:
        return 1.0
    try:
        return max(0.2, float(raw))
    except ValueError:
        return 1.0


def run_tui(api_url: str | None = None) -> None:
    resolved = api_url or os.getenv("HYPRCHAN_API_URL") or "http://localhost:8000/v1"
    HyprTUI(api_url=resolved, poll_interval=_read_poll_interval()).run()
