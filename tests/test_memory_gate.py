from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from core.hypraios.kernel.memory.memory_gate import MemoryGate
from core.hyprmemory.models import ConsolidationReport, DreamEntry, MemoryState


class _FakeMemoryService:
    def __init__(self) -> None:
        self.observe = AsyncMock()
        self.store_message = AsyncMock()
        self.sleep_consolidate = AsyncMock(
            return_value=ConsolidationReport(
                processed_items=3,
                episodes_written=1,
                facts_written=0,
                edges_written=0,
                dreams_written=0,
                fatigue_spent=3.0,
            )
        )
        self.fetch_dream_log = AsyncMock(return_value=[])


@pytest.mark.asyncio
async def test_observe_event_persists_meaningful_communication_events() -> None:
    gate = MemoryGate()
    gate.enabled = True
    memory = _FakeMemoryService()
    gate._resolve_memory_service = lambda: memory  # type: ignore[method-assign]

    await gate.observe_event(
        event_type="communication_message",
        payload={
            "id": 10,
            "origin": "communication_controller",
            "description": "hello there",
            "is_user": True,
        },
        state=MemoryState(f=1.0, v=0.0, e=0.8, a=0.3),
    )

    assert memory.observe.await_count == 1
    assert memory.store_message.await_count == 1
    assert memory.store_message.await_args is not None
    kwargs = memory.store_message.await_args.kwargs
    assert kwargs["role"] == "user"
    assert kwargs["kind"] == "perception.event"
    assert kwargs["content"] == "hello there"


@pytest.mark.asyncio
async def test_observe_event_skips_noisy_event_type_for_direct_item_persistence() -> (
    None
):
    gate = MemoryGate()
    gate.enabled = True
    memory = _FakeMemoryService()
    gate._resolve_memory_service = lambda: memory  # type: ignore[method-assign]

    await gate.observe_event(
        event_type="window_focus",
        payload={
            "id": 20,
            "origin": "windows_controller",
            "description": "active window changed",
            "is_user": False,
        },
        state=MemoryState(f=1.0, v=0.0, e=0.8, a=0.3),
    )

    assert memory.observe.await_count == 1
    assert memory.store_message.await_count == 0


@pytest.mark.asyncio
async def test_sleep_consolidate_returns_report() -> None:
    gate = MemoryGate()
    gate.enabled = True
    gate.sleep_enabled = True
    memory = _FakeMemoryService()
    gate._resolve_memory_service = lambda: memory  # type: ignore[method-assign]

    report = await gate.sleep_consolidate(budget_f=5.0)

    assert report is not None
    assert report.processed_items == 3
    assert gate.last_sleep_report is report


@pytest.mark.asyncio
async def test_fetch_dream_log_keeps_db_rows_and_returns_only_fresh_entries() -> None:
    gate = MemoryGate()
    gate.enabled = True
    gate.sleep_enabled = True
    memory = _FakeMemoryService()
    memory.fetch_dream_log = AsyncMock(
        side_effect=[
            [
                DreamEntry(
                    dream_id="d1",
                    ts=datetime.now(timezone.utc),
                    content="dream one",
                    episode_ids=["e1"],
                    source="llm_judge",
                )
            ],
            [
                DreamEntry(
                    dream_id="d1",
                    ts=datetime.now(timezone.utc),
                    content="dream one",
                    episode_ids=["e1"],
                    source="llm_judge",
                )
            ],
        ]
    )
    gate._resolve_memory_service = lambda: memory  # type: ignore[method-assign]

    first = await gate.fetch_dream_log()
    second = await gate.fetch_dream_log()

    assert len(first) == 1
    assert len(second) == 0
    assert memory.fetch_dream_log.await_count == 2
    assert memory.fetch_dream_log.await_args_list[0].kwargs["clear"] is False
