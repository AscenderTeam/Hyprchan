from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.hyprmemory.models.state import MemoryState, SemanticFeeling


@dataclass(slots=True)
class PerceptionTrace:
    """Raw perception trace stored in STM (lossless, TTL-bound)."""

    trace_id: str
    ts: datetime
    type: str
    payload: dict[str, Any]
    state: MemoryState
    session_id: str | None = None
    flags: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class STMItem:
    """Short-term memory item (message/event/tool result)."""

    item_id: str
    ts: datetime
    kind: str
    content: str
    meta: dict[str, Any]
    state: MemoryState
    salience: float = 0.0


@dataclass(slots=True)
class Episode:
    """Long-term episodic memory node."""

    episode_id: str
    ts_start: datetime
    ts_end: datetime
    gist: str
    entities: list[str]
    topics: list[str]
    emotion_vec: MemoryState
    semantic_feeling: SemanticFeeling
    source_trace_ids: list[str]
    embedding: list[float]
    salience: float
    version: int = 1


@dataclass(slots=True)
class SemanticFact:
    """Long-term semantic fact record."""

    fact_id: str
    subject: str
    predicate: str
    object: str
    qualifiers: dict[str, Any]
    confidence: float
    support_episode_ids: list[str]
    last_verified: datetime | None
    contradictions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class FactCandidate:
    """LLM-proposed semantic fact candidate."""

    subject: str
    predicate: str
    object: str
    confidence: float
    qualifiers: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EpisodeSummary:
    """LLM-proposed episodic summary elements."""

    gist: str
    entities: list[str]
    topics: list[str]


@dataclass(slots=True)
class ConceptNode:
    """Concept node used for associative recall graph."""

    concept_id: str
    kind: str
    name: str
    embedding: list[float]
    prior: float


@dataclass(slots=True)
class GraphEdge:
    """Graph edge between memory nodes."""

    edge_id: str
    src: str
    dst: str
    type: str
    weight: float
    ts: datetime
    decay_half_life_hours: float


@dataclass(slots=True)
class RecallBudget:
    """Recall budget controls for state-specific retrieval."""

    top_k: int = 8
    lexical_k: int = 6
    graph_hops: int = 2
    graph_top_m: int = 12


@dataclass(slots=True)
class MemoryQuery:
    """Recall query descriptor."""

    text: str
    state: MemoryState
    budget: RecallBudget = field(default_factory=RecallBudget)


@dataclass(slots=True)
class RecallResult:
    """Aggregated recall output."""

    episodes: list[Episode]
    facts: list[SemanticFact]
    concepts: list[ConceptNode]


@dataclass(slots=True)
class DreamEntry:
    """Dream log entry generated as consolidation side-effect."""

    dream_id: str
    ts: datetime
    content: str
    episode_ids: list[str]
    source: str


@dataclass(slots=True)
class ProceduralMemory:
    """Long-term procedural memory entry (skills/habits)."""

    memory_id: str
    name: str
    description: str
    tags: list[str]
    tool_sequence: list[dict[str, Any]]
    failure_notes: list[str]
    success_score: float
    embedding: list[float]

    def as_narrative(self) -> str:
        tags = ", ".join(self.tags) if self.tags else "none"
        failures = "; ".join(self.failure_notes) if self.failure_notes else "none"
        return (
            f"skill={self.name} | score={self.success_score:.2f}\n"
            f"description={self.description}\n"
            f"tags={tags}\n"
            f"failure_notes={failures}"
        )

    def to_dict(self):
        return {
            "memory_id": self.memory_id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "tool_sequence": self.tool_sequence,
            "failure_notes": self.failure_notes,
            "success_score": self.success_score,
        }


@dataclass(slots=True)
class ConsolidationReport:
    """Sleep consolidation output summary."""

    processed_items: int
    episodes_written: int
    facts_written: int
    edges_written: int
    dreams_written: int
    fatigue_spent: float
