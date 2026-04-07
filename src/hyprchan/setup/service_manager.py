from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from config.paths import repo_root


class ServiceManager:
    """
    Manages background daemon installation for Hyprchan.
    Supports systemd (Linux) and launchd (macOS).
    """

    def __init__(self):
        self.os_type = platform.system().lower()
        self.python_path = sys.executable
        self.hyprchan_bin = self._find_hyprchan_bin()

    def _find_hyprchan_bin(self) -> str:
        """Finds the 'hyprchan' executable path."""
        # Check if it's in PATH
        bin_path = shutil.which("hyprchan")
        if bin_path:
            return bin_path

        # Check common local locations (e.g. poetry/pip install)
        # If not found, we'll fall back to 'python -m hyprchan' or direct main.py
        # but the user said the command is 'hyprchan serve'
        return "hyprchan"

    def is_linux(self) -> bool:
        return self.os_type == "linux"

    def is_macos(self) -> bool:
        return self.os_type == "darwin"

    def install_service(self) -> bool:
        """Installs the background service for the current OS."""
        if self.is_linux():
            return self._install_linux_systemd()
        if self.is_macos():
            return self._install_macos_launchd()
        return False

    def _install_linux_systemd(self) -> bool:
        """Creates a systemd user service."""
        # Use 'hyprchan serve' as the command
        exec_start = f"{self.hyprchan_bin} serve"

        service_content = f"""[Unit]
Description=Hyprchan Autonomous AI Daemon
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
WorkingDirectory={repo_root()}
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""
        user_systemd_dir = Path.home() / ".config" / "systemd" / "user"
        user_systemd_dir.mkdir(parents=True, exist_ok=True)
        service_file = user_systemd_dir / "hyprchan.service"

        try:
            service_file.write_text(service_content, encoding="utf-8")
            # Reload and enable
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "--user", "enable", "hyprchan.service"], check=True)
            return True
        except (OSError, subprocess.CalledProcessError):
            return False

    def _install_macos_launchd(self) -> bool:
        """Creates a macOS launchd agent (plist)."""
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.hyprchan.daemon.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hyprchan.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{self.hyprchan_bin}</string>
        <string>serve</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{repo_root()}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>/tmp/hyprchan.err</string>
    <key>StandardOutPath</key>
    <string>/tmp/hyprchan.out</string>
</dict>
</plist>
"""
        try:
            plist_path.write_text(plist_content, encoding="utf-8")
            # Load the agent
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            subprocess.run(["launchctl", "load", str(plist_path)], check=True)
            return True
        except (OSError, subprocess.CalledProcessError):
            return False

    def start_service(self) -> bool:
        """Attempts to start the service immediately."""
        try:
            if self.is_linux():
                subprocess.run(["systemctl", "--user", "start", "hyprchan.service"], check=True)
                return True
            if self.is_macos():
                # Already started via 'load' if RunAtLoad is true, but just in case
                subprocess.run(["launchctl", "start", "com.hyprchan.daemon"], check=True)
                return True
        except (OSError, subprocess.CalledProcessError):
            return False
        return False
