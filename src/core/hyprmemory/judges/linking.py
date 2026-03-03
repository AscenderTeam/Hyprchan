from __future__ import annotations

from dataclasses import dataclass

from core.hyprmemory.models import ConceptNode, Episode, GraphEdge
from core.hyprmemory.utils.id import generate_id
from core.hyprmemory.utils.math import clamp, cosine_similarity
from core.hyprmemory.utils.text import lexical_similarity
from core.hyprmemory.utils.time import utc_now


@dataclass(slots=True)
class SimpleLinkingJudge:
    """Propose associative edges between episodes and concepts.

    Inspired by A-MEM's dynamic indexing/linking strategy (arXiv:2502.12110).
    """

    min_weight: float = 0.2
    decay_half_life_hours: float = 72.0

    def propose_edges(self, episode: Episode, concepts: list[ConceptNode]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for concept in concepts:
            text_sim = lexical_similarity(episode.gist, concept.name)
            vec_sim = cosine_similarity(episode.embedding, concept.embedding)
            weight = clamp(0.6 * vec_sim + 0.4 * text_sim, 0.0, 1.0)
            if weight < self.min_weight:
                continue
            edge = GraphEdge(
                edge_id=generate_id(),
                src=episode.episode_id,
                dst=concept.concept_id,
                type="semantic_sim",
                weight=weight,
                ts=utc_now(),
                decay_half_life_hours=self.decay_half_life_hours,
            )
            edges.append(edge)
        return edges
