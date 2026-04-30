from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from logging import Logger
from typing import Annotated, Any

from ascender.common import Injectable
from ascender.core import Inject, inject
from ascender.core.database import DatabaseEngine
from redis.asyncio import Redis

from hyprchan import settings
from hyprchan.core.hypraios.constants import Phases
from hyprchan.config.personalization import load_personalization_config
from hyprchan.core.hyprmemory.consolidation.sleep_consolidator import (
    ConsolidationConfig,
    SleepConsolidator,
)
from hyprchan.core.hyprmemory.interfaces import ConsolidationJudge, EmbeddingProvider
from hyprchan.core.hyprmemory.judges.linking import SimpleLinkingJudge
from hyprchan.core.hyprmemory.judges.llm_consolidation import LLMConsolidationJudge
from hyprchan.core.hyprmemory.judges.salience import WeightedSalienceJudge
from hyprchan.core.hyprmemory.judges.semantic_feeling import (
    DeterministicSemanticFeelingJudge,
)
from hyprchan.core.hyprmemory.layers.ltm_layer import LongTermMemoryLayer
from hyprchan.core.hyprmemory.layers.stm_layer import ShortTermMemoryLayer
from hyprchan.core.hyprmemory.layers.wm_layer import WorkingMemoryLayer
from hyprchan.core.hyprmemory.models import (
    ConsolidationReport,
    DreamEntry,
    MemoryQuery,
    MemoryState,
    PerceptionTrace,
    RecallBudget,
    RecallResult,
    STMItem,
)
from hyprchan.core.hyprmemory.services.retriever import HybridRetriever
from hyprchan.core.hyprmemory.skills import (
    PostgresProceduralStore,
    SqliteProceduralStore,
)
from hyprchan.core.hyprmemory.skills.memory import ProceduralMemory
from hyprchan.core.hyprmemory.stores.embedding_provider import OpenAIEmbeddingProvider
from hyprchan.core.hyprmemory.stores.ltm_postgres import PostgresLTMStore
from hyprchan.core.hyprmemory.stores.stm_memory import InMemorySTMStore
from hyprchan.core.hyprmemory.stores.stm_redis import RedisSTMStore
from hyprchan.core.hyprmemory.stores.vector_pg import PgVectorStore
from hyprchan.core.hyprmemory.utils.id import generate_id
from hyprchan.core.hyprmemory.utils.math import clamp
from hyprchan.core.hyprmemory.utils.time import utc_now


@dataclass(slots=True)
class MemoryServiceConfig:
    passive_budget: RecallBudget = field(
        default_factory=lambda: RecallBudget(top_k=4, lexical_k=3, graph_hops=1)
    )
    active_budget: RecallBudget = field(
        default_factory=lambda: RecallBudget(top_k=8, lexical_k=6, graph_hops=2)
    )
    maint_budget: RecallBudget = field(
        default_factory=lambda: RecallBudget(top_k=3, lexical_k=2, graph_hops=1)
    )


@Injectable(provided_in=None)
class HyprMemoryService:
    """Kernel-facing memory API for HyprChan."""

    def __init__(
        self,
        database: DatabaseEngine,
        logger: Annotated[Logger, Inject("ASC_LOGGER")],
    ) -> None:
        self.logger = logger
        self._init_error: str | None = None

        try:
            self._init(database)
        except Exception as exc:
            self._init_error = f"{type(exc).__name__}: {exc}"
            self.logger.error("HyprMemoryService failed to initialize: %s", exc, exc_info=True)
            self._set_degraded()

    def _init(self, database: DatabaseEngine) -> None:
        redis_client = self._resolve_redis()
        if redis_client:
            stm_store = RedisSTMStore(redis_client)
        else:
            self.logger.warning("Redis not available; using in-memory STM fallback.")
            stm_store = InMemorySTMStore()

        ltm_store = PostgresLTMStore(database)

        embedder: EmbeddingProvider | None = None
        vector_store = None
        try:
            embedder = self._resolve_embedder()
            vector_store = self._resolve_vector_store(ltm_store, embedder, database)
        except Exception as exc:
            self.logger.warning(
                "Vector store / embedder unavailable — recall and sleep consolidation disabled: %s", exc
            )

        try:
            dialect = database.engine.engine.dialect.name  # type: ignore[union-attr]
        except Exception:
            dialect = "sqlite"

        if dialect == "postgresql":
            skill_store = PostgresProceduralStore(database)
        else:
            skill_store = SqliteProceduralStore(database)

        self.stm_layer = ShortTermMemoryLayer(stm_store)
        self.ltm_layer = LongTermMemoryLayer(ltm_store)
        self.wm_layer = WorkingMemoryLayer()

        self.salience_judge = WeightedSalienceJudge()
        self.feeling_judge = DeterministicSemanticFeelingJudge()
        self.linking_judge = SimpleLinkingJudge()
        consolidation_judge = self._resolve_consolidation_judge()

        personalization = load_personalization_config()
        consolidation_config = ConsolidationConfig(k_sleep=float(personalization.memory.k_sleep))

        self._embedder_available = embedder is not None and vector_store is not None
        self.retriever = (
            HybridRetriever(ltm_store=ltm_store, vector_store=vector_store, embedder=embedder)  # type: ignore[arg-type]
            if self._embedder_available
            else None
        )
        self.consolidator = SleepConsolidator(
            stm_store=stm_store,
            ltm_store=ltm_store,
            embedder=embedder,  # type: ignore[arg-type]
            feeling_judge=self.feeling_judge,  # pyright: ignore[reportArgumentType]
            salience_judge=self.salience_judge,
            linking_judge=self.linking_judge,
            consolidation_judge=consolidation_judge,
            config=consolidation_config,
        )

        self.config = MemoryServiceConfig()
        self.__procedural_memory = ProceduralMemory(skill_store, embedder)

    def _set_degraded(self) -> None:
        """Initialize all attributes to safe no-op values when init fails."""
        stm_store = InMemorySTMStore()
        self.stm_layer = ShortTermMemoryLayer(stm_store)
        self.wm_layer = WorkingMemoryLayer()
        self.salience_judge = WeightedSalienceJudge()
        self.feeling_judge = DeterministicSemanticFeelingJudge()
        self.linking_judge = SimpleLinkingJudge()
        self._embedder_available = False
        self.retriever = None
        self.config = MemoryServiceConfig()
        # ltm_layer / consolidator / procedural_memory left unset; guarded in callers

    @property
    def procedural_memory(self) -> "ProceduralMemory | None":
        return getattr(self, "_HyprMemoryService__procedural_memory", None)

    async def observe(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        state: MemoryState,
        session_id: str | None = None,
        flags: dict[str, Any] | None = None,
    ) -> PerceptionTrace:
        """Record raw perception trace into STM."""
        trace = PerceptionTrace(
            trace_id=generate_id(),
            ts=utc_now(),
            type=event_type,
            payload=payload,
            state=state,
            session_id=session_id,
            flags=flags or {},
        )
        await self.stm_layer.observe(trace)
        return trace

    async def memorize_important(
        self,
        *,
        content: str,
        state: MemoryState,
        note: str = "",
    ) -> STMItem:
        """Store an agent-marked important memory in STM with maximum salience."""
        meta: dict[str, Any] = {"role": "assistant", "memorize": True}
        if note.strip():
            meta["note"] = note.strip()
        item = STMItem(
            item_id=generate_id(),
            ts=utc_now(),
            kind="memorize.important",
            content=content,
            meta=meta,
            state=state,
            salience=1.0,
        )
        await self.stm_layer.store_item(item)
        return item

    async def store_message(
        self,
        *,
        role: str,
        content: str,
        state: MemoryState,
        meta: dict[str, Any] | None = None,
        kind: str = "chat.message",
    ) -> STMItem:
        """Store a message/event into STM with salience estimation."""
        meta = meta or {}
        emotion_intensity = clamp(abs(state.v) + state.a, 0.0, 1.0)
        user_importance = 1.0 if role == "user" else 0.3
        salience = self.salience_judge.score(
            novelty=0.5,
            goal_rel=0.5,
            emotion_intensity=emotion_intensity,
            user_importance=user_importance,
        )
        item = STMItem(
            item_id=generate_id(),
            ts=utc_now(),
            kind=kind,
            content=content,
            meta={"role": role, **meta},
            state=state,
            salience=salience,
        )
        await self.stm_layer.store_item(item)
        return item

    async def recall(
        self,
        *,
        query_text: str,
        state: MemoryState,
        phase: Phases | None = None,
        budget: RecallBudget | None = None,
    ) -> RecallResult:
        """Recall memory candidates based on query + emotional state."""
        if self.retriever is None:
            return RecallResult(episodes=[], facts=[], concepts=[])
        budget = budget or self._budget_for_phase(phase)
        query = MemoryQuery(text=query_text, state=state, budget=budget)
        return await self.retriever.recall(query)

    async def recall_working_memory(
        self,
        *,
        query_text: str,
        state: MemoryState,
        phase: Phases | None = None,
        budget: RecallBudget | None = None,
    ) -> list[str]:
        """Compose working-memory prompt blocks for the LLM."""
        recall = await self.recall(
            query_text=query_text, state=state, phase=phase, budget=budget
        )
        blocks = self.wm_layer.compose(recall)
        return [f"[{block.title}]\n{block.content}" for block in blocks]

    async def recall_episodic(
        self,
        *,
        ts_from: datetime | None = None,
        ts_to: datetime | None = None,
        limit: int = 10,
    ) -> list[str]:
        """Recall episodes in a time range with rich narrative formatting."""
        ltm_layer = getattr(self, "ltm_layer", None)
        if ltm_layer is None:
            return []

        if ts_from is not None and ts_to is not None:
            episodes = await ltm_layer.episodes_in_range(ts_from=ts_from, ts_to=ts_to, limit=limit)
        else:
            episodes = await ltm_layer.recent_episodes(limit=limit)

        if not episodes:
            return []

        blocks: list[str] = []
        for ep in episodes:
            ts_start = ep.ts_start.strftime("%Y-%m-%d %H:%M")
            ts_end = ep.ts_end.strftime("%H:%M")
            lines = [f"[{ts_start} → {ts_end}]  (salience={ep.salience:.2f})", f"  {ep.gist}"]
            feeling = ep.semantic_feeling
            if feeling and feeling.label:
                cog = f" — {feeling.cognitive}" if feeling.cognitive else ""
                lines.append(f"  feeling: {feeling.label}{cog}")
            if ep.entities:
                lines.append(f"  entities: {', '.join(ep.entities)}")
            if ep.topics:
                lines.append(f"  topics: {', '.join(ep.topics)}")
            blocks.append("\n".join(lines))

        return blocks

    async def sleep_consolidate(self, budget_f: float) -> ConsolidationReport:
        """Run sleep-time consolidation (memory-bounded by fatigue budget)."""
        consolidator = getattr(self, "consolidator", None)
        if consolidator is None:
            return ConsolidationReport(
                processed_items=0, episodes_written=0, facts_written=0,
                edges_written=0, dreams_written=0, fatigue_spent=0.0,
            )
        return await consolidator.consolidate(budget_f)

    async def pending_stm(self) -> int:
        """Return number of pending STM items."""
        return await self.stm_layer.pending_count()

    async def fetch_dream_log(
        self, *, clear: bool = False, limit: int = 8
    ) -> list[DreamEntry]:
        """Fetch dream log entries accumulated during sleep consolidation."""
        ltm_layer = getattr(self, "ltm_layer", None)
        if ltm_layer is None:
            return []
        dreams = await ltm_layer.list_dreams(limit=limit)
        if clear and dreams:
            await ltm_layer.clear_dreams()
        return dreams

    def _budget_for_phase(self, phase: Phases | None) -> RecallBudget:
        if phase == Phases.MAINT:
            return self.config.maint_budget
        if phase == Phases.ACTIVE:
            return self.config.active_budget
        return self.config.passive_budget

    def _resolve_redis(self) -> Redis | None:
        fallback = object()
        redis_client = inject(Redis, fallback=fallback)
        if redis_client is fallback:
            return None
        return redis_client

    def _resolve_embedder(self) -> EmbeddingProvider:
        mode = os.getenv("HYPRMEMORY_EMBEDDINGS", "openai").strip().lower()
        if mode != "openai":
            raise RuntimeError(
                "Unsupported HYPRMEMORY_EMBEDDINGS mode. Use 'openai' with pgvector."
            )
        if not settings.OPENAI_OAUTH_TOKEN:
            raise RuntimeError("OPENAI_OAUTH_TOKEN is required for embeddings.")
        return OpenAIEmbeddingProvider(
            model=settings.OPENAI_EMBEDDING_MODEL,
            api_key=settings.OPENAI_OAUTH_TOKEN,
            base_url=settings.OPENAI_API_BASE_URL,
        )

    def _resolve_vector_store(
        self,
        ltm_store: PostgresLTMStore,
        embedder: EmbeddingProvider,
        database: DatabaseEngine,
    ):
        mode = os.getenv("HYPRMEMORY_VECTOR_STORE", "pgvector").strip().lower()
        if mode != "pgvector":
            raise RuntimeError("Unsupported HYPRMEMORY_VECTOR_STORE. Use 'pgvector'.")
        if "postgres" not in settings.DATABASE_CONNECTION.get("content", ""):
            raise RuntimeError("pgvector requires a Postgres connection string.")
        return PgVectorStore(database=database, ltm_store=ltm_store, embedder=embedder)

    def _resolve_consolidation_judge(self) -> ConsolidationJudge | None:
        mode = os.getenv("HYPRMEMORY_JUDGE", "heuristic").strip().lower()
        if mode != "llm":
            return None
        if not settings.OPENAI_OAUTH_TOKEN:
            self.logger.warning(
                "HYPRMEMORY_JUDGE=llm set but OPENAI_OAUTH_TOKEN missing."
            )
            return None
        temperature = float(os.getenv("HYPRMEMORY_JUDGE_TEMPERATURE", "0.4"))
        dream_temperature = float(os.getenv("HYPRMEMORY_DREAM_TEMPERATURE", "1.0"))
        return LLMConsolidationJudge(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_OAUTH_TOKEN,
            base_url=settings.OPENAI_API_BASE_URL,
            temperature=temperature,
            dream_temperature=dream_temperature,
        )
