# HyprAI OS Kernel Memory Integration Walkthrough

This document explains how HyprMemory is wired into the HyprAI OS kernel, including
the sleep/consolidation flow, buffer injection, and recall tools.

## Overview

The kernel integrates HyprMemory via `MemoryGate`. It provides:
- STM observation and message storage.
- Working-memory recall injected into the system prompt.
- A small chat buffer injected into active chat history.
- Sleep-time consolidation and dream-log injection.
- A `memory_recall` tool so Hyprchan can recall on demand.

## File Map

- `src/core/hypraios/kernel/memory/memory_gate.py`
  - Integration wrapper around `HyprMemoryService`.
  - Provides buffer injection, recall injection, and sleep hooks.
- `src/core/hypraios/kernel/kernel.py`
  - Calls memory observe/store/recall from the kernel loop.
  - Triggers sleep consolidation and queues dream logs.
- `src/core/hypraios/linguistic/linguistic_engine.py`
  - Injects memory recall into system prompt.
  - Appends last buffer messages into active chat history.
  - Pushes memory context to tool runtime.
- `src/core/hypraios/linguistic/tool_runtime.py`
  - Exposes `memory_recall` tool (on-demand recall).

## Configuration Flags

Set environment variables:

```
HYPRMEMORY_ENABLED=1
HYPRMEMORY_READ_ACTIVE=1        # optional, recall during ACTIVE
HYPRMEMORY_SLEEP_ENABLED=1      # enable sleep consolidation + dreams
HYPRMEMORY_BUFFER_LIMIT=3       # last N messages injected into chat history
HYPRMEMORY_BUFFER_KEY=hyprchan:wm_buffer
```

HyprMemory still requires pgvector + embeddings per:
`src/core/hyprmemory/WALKTHROUGH.md`.

## Data Flow (Awake)

1. **Perception -> STM**
   - `kernel.record_perception(...)` calls `memory_gate.observe_event(...)`.
   - This stores raw perception traces in STM.

2. **User messages -> Buffer (STM on eviction)**
   - User `communication_message` is appended into the working-memory buffer.
   - The message is stored in STM only when it is evicted from the buffer.

3. **Assistant outputs -> Buffer (STM on eviction)**
   - After inference, assistant output is appended into the buffer.
   - The output is stored in STM only when it is evicted from the buffer.

4. **Tool observations -> STM**
   - Tool results are stored as `tool.observation` items in STM.

5. **Recall -> System Prompt**
   - Before inference, the kernel builds a memory recall block using
     `memory_gate.build_system_prompt_injection(...)`.
   - This is injected into the system prompt (HYPRMEMORY RECALL block).

6. **Buffer Injection -> Active Chat**
   - The last `HYPRMEMORY_BUFFER_LIMIT` messages are appended to the
     active chat message list (deduped) so the LLM sees them as chat context.

## Sleep + Consolidation Flow

Sleep is handled in `HyprAIOSKernel._sleep_worker()`:

1. **Consolidation is triggered once sleep starts**
   - If `HYPRMEMORY_SLEEP_ENABLED=1`, the kernel runs:
     `memory_gate.sleep_consolidate(budget_f=pending_memory_units)`.
   - This runs concurrently with fatigue recovery.

2. **Dream log is fetched after consolidation completes**
   - After consolidation, the kernel calls:
     `memory_gate.fetch_dream_log()` which clears dream entries.
   - The dream log is queued for injection on the next wake.

3. **Dream injection**
   - `MemoryGate.build_system_prompt_injection(...)` injects a
     `SLEEP DREAM LOG` block once after wake.
   - The dream log is consumed only once and then cleared.

This keeps sleep consolidation and dream recall aligned with kernel phase transitions.

## On‑Demand Recall Tool

When `HYPRMEMORY_ENABLED=1`, the tool runtime exposes:

```
memory_recall(query: str)
```

The tool uses current kernel state (`f, v, e, a`) and phase to retrieve
episodic/semantic/associative memory blocks and returns them into the LLM context
as a tool result.

## Quick Usage Checklist

- Enable `HYPRMEMORY_ENABLED`.
- Ensure pgvector + embeddings are configured (see HyprMemory walkthrough).
- (Optional) Enable sleep consolidation with `HYPRMEMORY_SLEEP_ENABLED=1`.
- Send a message and confirm you see a HYPRMEMORY RECALL block in prompts.
- Trigger sleep (fatigue cap) and verify dream logs appear after wake.

## Maintenance Notes

- Memory buffering is bounded by `HYPRMEMORY_BUFFER_LIMIT`.
- Buffer storage uses Redis when available (`HYPRMEMORY_BUFFER_KEY`), falling back to in-memory list.
- Buffered chat messages are written to STM only on eviction (no collision with STM).
- Recall during ACTIVE is gated by `HYPRMEMORY_READ_ACTIVE`.
- Dream logs are injected once per wake cycle.
- If HyprMemory fails (missing DB or embeddings), memory integration safely no-ops.
