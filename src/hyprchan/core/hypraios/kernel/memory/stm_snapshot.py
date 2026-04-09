from __future__ import annotations

import json
import time
from logging import Logger
from pathlib import Path
from typing import Any


class StmSnapshotStore:
    def __init__(self, *, base_dir: Path, logger: Logger | None = None) -> None:
        self.base_dir = base_dir
        self.logger = logger
        self.stm_file = self.base_dir / "agent_memory.mem"
        self.hmem_file = self.base_dir / "agent_memory.hmem"

    def save(self, payload: dict[str, Any]) -> None:
        try:
            self.stm_file.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            if self.logger:
                self.logger.warning("Failed to save STM snapshot: %s", exc)

    def load(self) -> dict[str, Any] | None:
        if not self.stm_file.exists():
            return None

        try:
            data = json.loads(self.stm_file.read_text(encoding="utf-8"))
        except Exception as exc:
            if self.logger:
                self.logger.warning("Failed to load STM snapshot: %s", exc)
            return None

        if not isinstance(data, dict):
            return None

        return data

    def detect_crash_marker(self) -> bool:
        return self.hmem_file.exists()

    def touch_crash_marker(self) -> None:
        try:
            self.hmem_file.write_text(
                json.dumps({"started_at": time.time()}, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            if self.logger:
                self.logger.warning("Failed to create crash marker: %s", exc)

    def clear_crash_marker(self) -> None:
        try:
            if self.hmem_file.exists():
                self.hmem_file.unlink()
        except Exception as exc:
            if self.logger:
                self.logger.warning("Failed to clear crash marker: %s", exc)
