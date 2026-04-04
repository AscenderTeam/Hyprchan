# HyprMemory Walkthrough

## Overview
HyprMemory provides a layered, brain-inspired memory stack for HyprChan:

- **STM (Short-term)**: Redis/in-memory TTL store for raw perception + recent items.
- **LTM (Long-term)**: Postgres storage for episodes, semantic facts, concepts, graph edges, and dream logs.
- **WM (Working-memory)**: Prompt blocks composed from recall results.
- **Retrieval**: Hybrid dense + lexical + graph spreading activation with emotion-aware reranking.
- **Consolidation**: Sleep-time STM -> LTM distillation with fatigue-bounded processing.
- **Dreams**: Optional LLM judge generates a dream fragment as a consolidation side-effect.

All core APIs are surfaced in `HyprMemoryService` for easy integration with HyprAI OS.

## File Map

- `src/core/hyprmemory/services/memory_service.py`
  - Main API: `observe`, `store_message`, `recall`, `recall_working_memory`, `sleep_consolidate`, `fetch_dream_log`.
- `src/core/hyprmemory/services/retriever.py`
  - Hybrid recall + spreading activation.
- `src/core/hyprmemory/consolidation/sleep_consolidator.py`
  - STM -> LTM consolidation, LLM judge integration, dream accumulation.
- `src/core/hyprmemory/layers/*.py`
  - WM/STM/LTM access layers.
- `src/core/hyprmemory/judges/*.py`
  - Salience, semantic feeling, linking, and LLM consolidation judges.
- `src/core/hyprmemory/stores/*.py`
  - Redis STM, Postgres LTM, pgvector search, local vector fallback, embedding providers.
- `src/core/hyprmemory/models/*.py`
  - Dataclasses for memory objects and query results.
- `src/entities/*.py`
  - SQLAlchemy ORM entities for Postgres, including `DreamEntity`.

## Database Setup

The ORM is configured in `src/settings.py` to use a Postgres connection string:

- `DATABASE_URL` (env) overrides the default
- Default: `postgresql+asyncpg://postgres:postgres@localhost:5432/hyprchan`

Registered entities:

- `entities.episode`
- `entities.fact`
- `entities.concept`
- `entities.edge`
- `entities.dream`

### PgVector

To use pgvector-backed similarity search:

1. Ensure the extension is enabled in Postgres:

```
CREATE EXTENSION IF NOT EXISTS vector;
```

2. Set a vector dimension that matches your embedding model:

```
HYPRMEMORY_VECTOR_DIM=1536
```

3. (Optional) Force pgvector usage:

```
HYPRMEMORY_VECTOR_STORE=pgvector
```

pgvector is required. The service will fail fast if the extension or Postgres
connection is missing.

## Redis STM

If Redis is available, STM uses `RedisSTMStore` with TTL. If not, it falls back to
`InMemorySTMStore` with TTL eviction. To control Redis injection, register a Redis
provider in Ascender DI (or adjust the store wiring in `HyprMemoryService`).

## Embeddings

Embeddings are required. The service will fail fast if embeddings are not configured.
To use OpenAI embeddings, set:

```
HYPRMEMORY_EMBEDDINGS=openai
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

`HyprMemoryService` will then use `OpenAIEmbeddingProvider` with `OPENAI_OAUTH_TOKEN`.

## LLM Judges (Pluggable)

To enable LLM judges during sleep consolidation, set:

```
HYPRMEMORY_JUDGE=llm
```

Optional tuning:

```
HYPRMEMORY_JUDGE_TEMPERATURE=0.4
HYPRMEMORY_DREAM_TEMPERATURE=1.0
```

When enabled, the LLM judge will:

- Summarize episodes (gist, entities, topics)
- Extract semantic facts (subject, predicate, object)
- Generate a dream fragment after consolidation completes

## Core API Usage

### Observe perception

```py
await memory.observe(
    event_type="workspace_switch",
    payload={"workspace_id": "2"},
    state=MemoryState(f=10, v=0.1, e=0.6, a=0.4),
)
```

### Store a message

```py
await memory.store_message(
    role="user",
    content="I prefer concise replies.",
    state=MemoryState(f=8, v=0.2, e=0.7, a=0.3),
)
```

### Recall

```py
result = await memory.recall(
    query_text="preferences about responses",
    state=MemoryState(f=6, v=0.1, e=0.7, a=0.2),
    phase=Phases.ACTIVE,
)
```

### Sleep consolidation

```py
report = await memory.sleep_consolidate(budget_f=12.0)
```

### Fetch dream log

```py
dreams = await memory.fetch_dream_log(clear=True, limit=4)
for dream in dreams:
    print(dream.content)
```

## HyprAI OS Integration Plan

HyprAI OS kernel can call:

- `observe(...)` when perception events are recorded
- `store_message(...)` for user/assistant/tool messages
- `recall(...)` during ACTIVE/PASSIVE cycles (budgeted by phase)
- `sleep_consolidate(...)` during SLEEP with `budget_f` tied to fatigue burn-down
- `fetch_dream_log(...)` on wake to inject a `SLEEP DREAM LOG` system message

This keeps memory fully coupled to the `f, v, e, a` state vector while preserving
kernel phase boundaries.

## Notes / Next Extensions

- Add reranking or reranker models if desired.
- Replace the heuristic gist/fact extraction with a stronger LLM judge prompt.
- Add concept deduplication (by name or embedding similarity).
