# HyprChan Memory System – Implementation Documentation Plan

> Goal: design a brain-like memory stack for HyprChan with layered storage (WM/STM/LTM), associative recall, episodic reasoning, and sleep-time consolidation that consumes **f (fatigue)**.
>
> This document is a **plan + spec** you can adapt later to HyprChan’s current kernel architecture (once you upload the current implementation doc).

---

## 0. Scope and non-goals

### In scope
- Layered memory: **Working**, **Short-term**, **Long-term** (episodic + semantic + optional procedural)
- **Perception signals** stored as raw traces + distilled episodes
- **Associative recall** via a memory graph (spreading activation)
- **Episodic reasoning** over retrieved chains
- States: **PASSIVE**, **ACTIVE**, **SLEEP** and how HyprChan reads/writes memory in each
- Deterministic “judge” projection: internal numeric signals → **semantic feeling** representation

### Non-goals (for v1)
- Full SpatialRAG / physical 3D mapping (defer)
- Multi-agent shared memory federation (defer)
- Perfect psychological fidelity (we approximate)

---

## 1. Terminology

- **WM (Working Memory)**: prompt/context window composition
- **STM (Short-term Memory)**: temporary recent store (RAM/Redis/local DB w/ TTL)
- **LTM (Long-term Memory)**: durable store
  - **Episodic**: time-stamped events/episodes ("what happened")
  - **Semantic**: stable facts/preferences/rules ("what is true")
  - **Procedural** (optional): workflows/skills
- **Perception signal**: raw sensory/system events (face detected, UI changes, timers, audio features, etc.)
- **Episode**: an aggregated slice of experience (time window) built from multiple signals/messages
- **Concept node**: abstract label (topic/entity/emotion/goal) used for associative graph recall
- **f (fatigue)**: consolidation budget consumed in SLEEP

---

## 2. System architecture overview

### 2.1 Components
1. **Memory API (Kernel-facing)**
   - `observe(signal)`
   - `store_message(role, content, meta)`
   - `recall(query, state, budget)`
   - `sleep_consolidate(budget_f)`
   - `commit_episode()` (optional boundary)

2. **Stores**
   - **STM Store**: fast, TTL-based
   - **LTM Stores**:
     - **Vector index** for similarity search (episodes + concepts)
     - **Graph store** for associative recall (nodes + edges)
     - **Timeline store** for time queries
     - **Semantic fact store** (triples + confidence)

3. **Judge models** (deterministic, schema-bound)
   - **Semantic Feeling Judge**: maps numeric state + recent signals → semantic feeling struct
   - **Salience Judge**: estimates importance/novelty/goal relevance
   - **Linking Judge**: proposes edges between nodes during consolidation

4. **Retriever + Reranker**
   - Hybrid candidate retrieval: dense + lexical
   - Graph expansion: spreading activation
   - Emotion-aware reranking

5. **Consolidator (Sleep/Hippocampus)**
   - Aggregates STM → episodes
   - Extracts facts
   - Builds/updates graph
   - Prunes / decays

---

## 3. Kernel phases: PASSIVE / ACTIVE / MAINT / SLEEP (aligned to HyprAI OS spec)

> Source of truth for phases + loop behavior: **HyprAI OS — Perception → Mood Dynamics Specification** (uploaded). fileciteturn2file0L64-L72

HyprAI OS runs a **continuous kernel loop** except in **SLEEP**, and perception primarily **preempts timing** (cooldown), not cognition. fileciteturn2file0L9-L17 fileciteturn2file0L52-L62

### 3.1 PASSIVE (slow background awareness, still “alive”)
**Definition:** Kernel loop is running; HyprChan is not being directly poked by the user, but she continues background awareness and self-thought.

**Key correction:** PASSIVE is *not* “no recall / no tools.” It is a low-tempo loop phase where HyprChan can still think, accumulate STM, and use tools, typically on a cooldowned self-loop.

**Reads:**
- Full `recall()` is allowed, but should be **budgeted** (smaller topK, fewer graph hops) unless attention pressure is high.

**Writes:**
- Append raw perception to **STM.raw_trace** (TTL)
- Append self-thought ticks / tool results to STM
- Update passive pressure metrics (event weights)

**Policy:**
- Lower token + tool budgets per tick
- Prefer “maintenance” operations: lightweight clustering, edge decay, cache refresh

### 3.2 ACTIVE (engaged; user- or self-activated)
**Definition:** Kernel loop is engaged for interaction or attention closure.

ACTIVE can be entered as:
- **USER‑ACTIVATED** via CommunicationController, even if currently SLEEP/MAINT under safe conditions. fileciteturn2file0L30-L35
- **SELF‑ACTIVATED** when attention pressure/loop closure requires engagement, with higher fatigue cost and single attempt. fileciteturn2file0L76-L96

**Reads/Writes:**
- Same as PASSIVE, but with larger budgets and stronger goal-driven retrieval.

### 3.3 MAINT (load shedding / cooldown)
**Definition:** Safety/load-control phase where the system reduces work to protect stability.

**Policy:**
- No heavy consolidation; only essential memory writes
- Reduce tool usage and retrieval hops

### 3.4 SLEEP (loop halted; consolidation only)
**Definition:** Kernel loop is halted; only memory consolidation runs.

**Key rule:** Sleep is **memory-bounded**, not time-bounded: it continues until pending memory is processed **or** fatigue reaches 0 (whichever comes first). fileciteturn2file0L123-L141

**Reads:**
- Pull all STM items pending consolidation

**Writes:**
- Write episodic nodes + embeddings
- Extract/merge semantic facts
- Create/strengthen associative edges
- Apply pruning/decay

---

## 4. Data formats

### 4.1 Common IDs and timestamps
- `id`: UUID/ULID
- `ts`: ISO 8601 with timezone
- `source`: kernel module identifier (chat/perception/system/tool)

### 4.2 Raw Perception Trace (STM)
Stored “as-is” (no loss) but TTL-bound.

```json
{
  "trace_id": "ulid",
  "ts": "2026-03-03T18:40:12+05:00",
  "type": "perception.face_detected",
  "payload": { "detected": false, "confidence": 0.92 },
  "state": { "f": 0.55, "v": -0.12, "e": 0.30, "a": 0.61 },
  "session_id": "ulid",
  "flags": { "important": false, "user_present": false }
}
```

### 4.3 STM Message/Event
```json
{
  "item_id": "ulid",
  "ts": "...",
  "kind": "chat.message" | "tool.result" | "system.event" | "perception.*",
  "content": "...",
  "meta": { "role": "user|assistant|tool", "tool_name": "..." },
  "state": { "f": 0.22, "v": 0.40, "e": 0.72, "a": 0.33 },
  "salience": 0.0
}
```

### 4.4 Episodic Memory Node (LTM)
```json
{
  "episode_id": "ulid",
  "ts_start": "...",
  "ts_end": "...",
  "gist": "Short natural summary of what happened.",
  "entities": ["user", "hyprchan", "app:hyprland"],
  "topics": ["sleep", "memory", "coding"],
  "emotion_vec": { "f": 0.70, "v": -0.20, "e": 0.25, "a": 0.60 },
  "semantic_feeling": {
    "label": "restless loneliness",
    "cognitive": "strained but alert",
    "motivation": "seeking engagement",
    "stability": 0.42
  },
  "source_trace_ids": ["..."],
  "embedding": "<vector_ref>",
  "salience": 0.73,
  "version": 1
}
```

### 4.5 Semantic Fact Record (LTM)
Prefer explicit grounding to episode sources.

```json
{
  "fact_id": "ulid",
  "triple": {"s": "user", "p": "prefers", "o": "concise replies"},
  "qualifiers": {"start": "...", "end": null, "point": null},
  "confidence": 0.78,
  "support_episode_ids": ["..."],
  "last_verified": "...",
  "contradictions": []
}
```

### 4.6 Concept Node (Graph)
Used for associative recall (entities/topics/feelings/goals).

```json
{
  "concept_id": "ulid",
  "kind": "entity|topic|feeling|goal",
  "name": "restless loneliness",
  "embedding": "<vector_ref>",
  "prior": 0.10
}
```

### 4.7 Graph Edge
```json
{
  "edge_id": "ulid",
  "src": "node_id",
  "dst": "node_id",
  "type": "temporal_next|shared_entity|semantic_sim|emotion_sim|causal|repetition",
  "weight": 0.0,
  "ts": "...",
  "decay_half_life_hours": 72
}
```

---

## 5. Storage model (recommended)

### 5.1 Minimal DB layout
- `stm_items` (TTL)
- `episodes` (LTM)
- `facts` (LTM)
- `concepts` (LTM)
- `edges` (LTM graph)
- `episode_embeddings` / `concept_embeddings` (vector index; can be external)
- **PGVector** required for `episodes.embedding` and `concepts.embedding` with a fixed dimension

### 5.2 Indexing guidance
- `episodes(ts_end)` for time filtering
- `facts(triple.s, triple.p)` for preference queries
- `edges(src)`, `edges(dst)` for traversal
- Vector index supports `topK(query_embedding)` for episodes + concepts

---

## 6. Core formulas (simple + understandable, grounded in MemGPT, REMem, Synapse, Emotional RAG, and A-Mem research)

> This section operationalizes mechanisms inspired by:
> - **MemGPT (2310.08560)** – memory hierarchy and externalized recall control
> - **REMem (2602.13530)** – episodic gists + fact triples + temporal qualifiers
> - **Synapse (2601.02744)** – spreading activation, hybrid retrieval, temporal decay
> - **Emotional RAG (2410.23041)** – emotion-aware retrieval via state vectors
> - **A-Mem (2502.12110)** – self-evolving linked memory notes
>
> The formulas below are simplified, implementable versions of mechanisms described in these works, adapted to HyprChan’s architecture.

> Note: papers often present variants; we’ll use clear implementable versions.

### 6.1 Salience score (what’s worth keeping)
A weighted sum of signals:

- `novelty` (how new/unexpected)
- `goal_rel` (relevant to current task/goals)
- `emotion_intensity` (|valence| + arousal)
- `user_importance` (explicit preference, instruction, or long-term identity info)

**Formula:**

`salience = clamp( wN*novelty + wG*goal_rel + wE*emotion_intensity + wU*user_importance , 0, 1 )`

### 6.2 Temporal recency decay (older memories fade)
Use exponential decay:

`recency(t) = exp( - (now - t) / tau )`

where `tau` is a time constant (e.g. 7 days).

### 6.3 Emotion similarity (state-congruent recall)
Represent emotion as a vector `z = [f, v, e, a]`.

Option A (cosine similarity):

`sim_emotion = cosine(z_query, z_memory)`

Option B (distance to similarity):

`sim_emotion = exp( - ||z_query - z_memory||_2 / sigma )`

### 6.4 Hybrid candidate retrieval score (dense + lexical + recency)

`score_candidate = wS*sim_semantic + wL*sim_lexical + wR*recency + wP*prior_salience`

- `sim_semantic`: cosine between query embedding and memory embedding
- `sim_lexical`: BM25-like score (or keyword overlap proxy)
- `prior_salience`: stored salience of memory

### 6.5 Spreading activation (associative recall)
We start with anchor activations `a0(node)` from candidate retrieval.

For `k` steps (hops):

`a_{k+1}(j) += sum_i ( a_k(i) * w(i->j) * decay_k )`

Where:
- `w(i->j)` is edge weight
- `decay_k` decreases with hop count (e.g. `decay_k = alpha^k`, alpha in (0,1))

**Optional inhibition (sparsity):** after each hop keep only top-M activated nodes and zero the rest.

### 6.6 Final recall ranking (triple-signal)
Combine semantic similarity + activation + graph prior:

`score_final = w1*sim_semantic + w2*a(node) + w3*graph_prior(node) + w4*sim_emotion`

- `graph_prior(node)` can be a simple centrality or stored prior

### 6.7 Fatigue dynamics + sleep processing (aligned to HyprAI OS spec)

In HyprAI OS, fatigue **accumulates** during inference and passive perception, and **burns down during sleep** proportional to how much memory is processed.

**Accumulation (examples):**
- Per inference:

`f += k_tok * tokens + k_inf + k_self(if SELF)` fileciteturn2file0L107-L114

- Per passive perception:

`f += k_evt * event_weight` fileciteturn2file0L115-L118

**Sleep is memory-bounded:**
Let:
- `M_total` = total pending memory units queued for consolidation
- `M_processed` = processed so far

Per sleep iteration:

`ΔM = min(M_step, M_total − M_processed)`

`M_processed += ΔM` fileciteturn2file0L123-L131

Fatigue reduction is proportional to processed memory:

`f -= k_sleep * ΔM` fileciteturn2file0L133-L136

Termination:
- if `M_processed >= M_total` → exit sleep (with `f = max(0, f)`) fileciteturn2file0L138-L141
- if `f <= 0` → sleep may end even if backlog remains (kernel policy), otherwise continue until backlog is cleared.

---

## 7. Retrieval behavior by state

### 7.1 PASSIVE recall (background loop)
PASSIVE still runs the **inference / memory / phase engine** on a cooldowned self-loop. fileciteturn2file0L19-L28 fileciteturn2file0L64-L72

**Default behavior:**
- Recall is enabled, but **budgeted**:
  - smaller candidate topK
  - fewer spreading-activation hops
  - stronger recency bias
- Tools are enabled, but the kernel’s cooldown/tempo controls how often self-thought ticks occur.

**Goal:** accumulate STM + maintain associative structures without burning too many tokens.

### 7.2 ACTIVE recall
**Pipeline:**
1) Build query representation:
   - `q_text` = current user request + current task
   - `z_query` = current [f,v,e,a]
2) Candidate pull:
   - vector topK episodes + concepts
   - lexical topK (BM25/keywords)
3) Anchor activations from candidates
4) Spreading activation expansion (2–4 hops)
5) Rerank with `score_final`
6) Bundle output into WM blocks:
   - “Relevant episodes” (gists)
   - “Facts/preferences” (semantic)
   - “Useful procedures” (optional)

### 7.3 SLEEP recall
- Not used for answering user.
- Used for consolidation only:
  - fetch STM items not consolidated
  - fetch related LTM neighborhoods for linking

---

## 8. Consolidation algorithm (SLEEP)

### 8.1 Inputs
- STM items since last sleep
- Current state vector `z_sleep`
- Remaining fatigue budget `(1.0 - f)`

### 8.2 Steps
1) **Batching / episode segmentation**
   - Group STM by session + time gaps (e.g. new episode if gap > 10 min)
2) **Episode synthesis**
   - Create `gist`, `entities`, `topics`
   - Attach `source_trace_ids`
3) **Semantic feeling projection (judge)**
   - Produce `semantic_feeling` from numeric state + signals
   - Must be schema-locked; cannot invent events
4) **Salience compute**
   - Compute `salience` via formula + judge (bounded)
5) **Write LTM**
   - Insert episodic node + embedding
6) **Fact extraction**
   - Create/merge triples with confidence, link to episode
7) **Graph linking**
   - Add edges:
     - temporal_next (episode_i → episode_{i+1})
     - shared_entity/topic
     - semantic_sim (if above threshold)
     - emotion_sim (if above threshold)
   - Update existing edges (strengthen)
8) **Prune/decay**
   - Apply time decay to edge weights
   - Remove edges below epsilon
   - Optionally archive low-salience raw traces
9) **Fatigue burn**
   - compute `cost` and update `f`
   - stop if `f>=1.0`

### 8.3 Dream side effect (LLM judge)
When LLM consolidation is enabled, the judge may emit a **dream fragment** as a side effect.
This fragment is **not** treated as a factual memory. It is stored in a separate
`dream_log` and injected to HyprChan on wake as a **SLEEP DREAM LOG** system message.

Rules:
- Dreams are derived from consolidated episodes.
- They may be vivid or metaphorical, but should not be asserted as truth.
- The dream log is cleared after being consumed.

---

## 9. Deterministic Judge specs

### 9.1 Semantic Feeling Judge
**Purpose:** translate numeric internal state + recent signals into a semantic descriptor for storage/retrieval.

**Rules:**
- Must not create new facts/events.
- Only interprets *given* signals.
- Output must match strict JSON schema.

**Output schema:**
```json
{
  "label": "...",
  "cognitive": "...",
  "motivation": "...",
  "stability": 0.0
}
```

### 9.2 Salience Judge
Outputs bounded [0,1] suggestions and “why tags”:
- `emotion_intense`, `goal_relevant`, `user_preference`, `novel`, `danger`, etc.

### 9.3 Linking Judge
Given a new episode, propose top-N edges to existing nodes:
- reason must cite shared entity/topic/feeling/temporal proximity

### 9.4 LLM Consolidation Judge (pluggable)
Optional LLM judge (LangChain-backed) that can replace heuristic steps during sleep:
- Episode summary (gist/entities/topics)
- Fact extraction
- Dream fragment generation (side effect)

---

## 10. Implementation milestones

### Milestone A – Layered memory baseline
- STM store + WM builder
- LTM episodic store + vector index

### Milestone B – Sleep consolidation
- Episode segmentation
- Gist + embedding
- Fatigue burn

### Milestone C – Associative graph
- Concepts + edges tables
- Spreading activation retrieval

### Milestone D – Semantic facts
- Triple extraction + confidence
- Preference recall

### Milestone E – Emotion-aware recall
- Semantic feeling judge
- Emotion similarity rerank

---

## 11. Integration hooks (to adapt to HyprChan kernel later)

When you upload the current kernel doc, we will map:
- Kernel states → PASSIVE/ACTIVE/SLEEP triggers
- Existing event IDs / trace formats → STM schema
- Existing memory JSON → migration plan
- Existing internal state update loop (f/v/e/a) → judge inputs and retrieval bias
- Existing tool protocol → `recall()` and `sleep_consolidate()` APIs

---

## 12. Appendix: Example WM (Working Memory) assembly

WM should be assembled as blocks, not a raw dump:
1) `Current state` (short)
2) `Current task/goals`
3) `Relevant facts` (semantic)
4) `Relevant episodes` (episodic gists)
5) `Recent dialogue` (rolling window)

Token budgeting is enforced per block.
