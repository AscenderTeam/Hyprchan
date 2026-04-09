from __future__ import annotations

from dataclasses import dataclass

from hyprchan.core.hyprmemory.models import RecallResult


@dataclass(slots=True)
class WorkingMemoryBlock:
    """Renderable working memory block for LLM prompts."""

    title: str
    content: str


class WorkingMemoryLayer:
    """Working memory composer for prompt assembly."""

    def compose(self, recall: RecallResult) -> list[WorkingMemoryBlock]:
        """Compose WM blocks from recall results."""
        blocks: list[WorkingMemoryBlock] = []

        if recall.episodes:
            episodes_text = "\n".join(
                f"- {episode.gist} ({episode.ts_start.isoformat()}->{episode.ts_end.isoformat()})"
                for episode in recall.episodes
            )
            blocks.append(WorkingMemoryBlock(title="Relevant Episodes", content=episodes_text))

        if recall.facts:
            facts_text = "\n".join(
                f"- {fact.subject} {fact.predicate} {fact.object} (conf={fact.confidence:.2f})"
                for fact in recall.facts
            )
            blocks.append(WorkingMemoryBlock(title="Facts & Preferences", content=facts_text))

        if recall.concepts:
            concepts_text = ", ".join(concept.name for concept in recall.concepts)
            blocks.append(WorkingMemoryBlock(title="Concept Anchors", content=concepts_text))

        return blocks
