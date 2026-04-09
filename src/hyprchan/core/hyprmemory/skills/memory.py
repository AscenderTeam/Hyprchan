from typing import Any

from hyprchan.core.hyprmemory.interfaces import EmbeddingProvider
from hyprchan.core.hyprmemory.interfaces.stores import ProceduralMemory as ProcMem
from hyprchan.core.hyprmemory.interfaces.stores import ProceduralMemoryStore


class ProceduralMemory:
    def __init__(
        self, store: ProceduralMemoryStore, embeddings: EmbeddingProvider | None = None
    ) -> None:
        self.store = store
        self.embeddings = embeddings

    async def save_skill(
        self,
        name: str,
        content: str,
        tags: list[str] | None = None,
        success_score: float = 0.0,
        tool_sequence: list[dict[str, Any]] | None = None,
    ):
        await self.store.upsert(
            ProcMem(
                memory_id=name,
                name=name,
                description=content,
                tags=tags or [],
                tool_sequence=tool_sequence or [],
                failure_notes=[],
                success_score=success_score,
                embedding=(await self.embeddings.embed(content))
                if self.embeddings
                else [],
            )
        )

        return {
            "status": "SUCCESS",
            "message": f"Congratulations with new skill! Remember that `{name}` can be patched anytime you need, do not create NEW skill that is related to `{name}`",
        }

    async def recall_skill(self, query: str, max: int = 20):
        result = await self.store.query(query, limit=max)
        return {
            "status": "SUCCESS",
            "memory_logs": [item.as_narrative() for item in result],
        }

    async def list_skills(self, max: int = 20):
        result = await self.store.list_recent(max)
        return {
            "status": "SUCCESS",
            "memory_logs": [item.as_narrative() for item in result],
        }

    async def patch_skill(
        self,
        name: str,
        content: str,
        failure_notes: list[str],
        success_score: float | None = None,
        tool_sequence: list[dict[str, Any]] | None = None,
    ):
        skill = await self.store.fetch_by_name(name)

        if not skill:
            return {
                "status": "ERROR",
                "message": f"You don't have skill named `{name}`, try recalling the correct name, if you can't find, use `save_skill` tool to create new skill.",
            }

        memory_id = skill.memory_id
        await self.store.upsert(
            ProcMem(
                memory_id=memory_id,
                name=skill.name,
                description=content,
                tags=skill.tags,
                tool_sequence=tool_sequence or skill.tool_sequence,
                failure_notes=failure_notes,
                success_score=success_score or skill.success_score,
                embedding=skill.embedding,
            )
        )

        return {
            "status": "SUCCESS",
            "message": f"You patched your skill! Remember that `{name}` can be patched anytime you need, do not create NEW skill that is related to `{name}`, we don't need duplicates!",
        }
