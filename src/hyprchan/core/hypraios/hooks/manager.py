from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from logging import Logger
from hyprchan.core.hypraios.hooks.types import HookFn, HookName, HookPayload, HookResult


@dataclass(slots=True)
class _HookEntry:
    name: HookName
    fn: HookFn
    priority: int
    once: bool


class HookManager:
    def __init__(self, logger: Logger | None = None) -> None:
        self._logger = logger
        self._hooks: dict[HookName, list[_HookEntry]] = {}

    def register(
        self,
        name: HookName,
        fn: HookFn,
        *,
        priority: int = 0,
        once: bool = False,
    ) -> None:
        entry = _HookEntry(name=name, fn=fn, priority=priority, once=once)
        self._hooks.setdefault(name, []).append(entry)
        self._hooks[name].sort(key=lambda item: item.priority, reverse=True)

    def unregister(self, name: HookName, fn: HookFn) -> None:
        entries = self._hooks.get(name)
        if not entries:
            return
        self._hooks[name] = [entry for entry in entries if entry.fn is not fn]

    def clear(self, name: HookName | None = None) -> None:
        if name is None:
            self._hooks.clear()
            return
        self._hooks.pop(name, None)

    async def fire(
        self,
        name: HookName,
        payload: HookPayload,
    ) -> HookPayload:
        entries = list(self._hooks.get(name, []))
        if not entries:
            return payload

        for entry in entries:
            try:
                result = entry.fn(payload)
                if isawaitable(result):
                    result = await result
            except Exception as exc:
                if self._logger:
                    self._logger.warning(
                        "Hook %s failed in %s: %s", name, entry.fn, exc
                    )
                continue

            if isinstance(result, HookResult):
                if result.payload:
                    payload.update(result.payload)
                if result.stop:
                    if entry.once:
                        self.unregister(name, entry.fn)
                    break
            elif isinstance(result, dict):
                payload.update(result)

            if entry.once:
                self.unregister(name, entry.fn)

        return payload
