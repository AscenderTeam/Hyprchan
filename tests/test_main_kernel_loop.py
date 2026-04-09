import asyncio

import pytest

from core.hypraios.kernel.main_loop import MainKernelLoop


class _Param:
    def __init__(self, value: float) -> None:
        self.value = value


def test_tick_respects_cooldown_window() -> None:
    loop = MainKernelLoop(_Param(1.0), _Param(0.5))
    loop.cooldown.value = 0.0

    first = loop.tick(now=10.0)
    second = loop.tick(now=10.01)
    third = loop.tick(now=10.2)

    assert first is False
    assert second is True
    assert third is True


def test_perception_signal_reduces_cooldown_and_wakes_loop() -> None:
    loop = MainKernelLoop(_Param(1.0), _Param(0.25))
    loop.cooldown.value = 1.0

    loop.perception_signal()

    assert loop.cooldown.value == 0.25
    assert loop._wake_event.is_set() is True


@pytest.mark.asyncio
async def test_loop_invokes_callback_and_resets_cooldown() -> None:
    loop = MainKernelLoop(_Param(2.0), _Param(0.5))
    calls = 0

    async def _callback() -> None:
        nonlocal calls
        calls += 1
        await loop.stop()

    loop.loop_dt.value = 0.01
    loop.cooldown_floor = 0.005

    await asyncio.wait_for(loop.loop(_callback), timeout=0.2)

    assert calls == 1
    assert loop.cooldown.value == pytest.approx(0.02)
