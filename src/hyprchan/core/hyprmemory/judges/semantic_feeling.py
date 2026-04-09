from __future__ import annotations

from dataclasses import dataclass

from core.hyprmemory.models import MemoryState, SemanticFeeling
from core.hyprmemory.utils.math import clamp


@dataclass(slots=True)
class DeterministicSemanticFeelingJudge:
    """Project scalar state into a semantic feeling descriptor.

    Deterministic judge inspired by Emotional RAG's state-aware retrieval framing
    (see "Emotional RAG: Integrating Affective State into Retrieval-Augmented Generation",
    arXiv:2410.23041).
    """

    f_max: float = 100.0

    def project(self, state: MemoryState) -> SemanticFeeling:
        v = state.v
        a = state.a
        e = state.e
        f_norm = clamp(state.f / self.f_max, 0.0, 1.0)

        if v >= 0.35:
            valence = "positive"
        elif v <= -0.35:
            valence = "negative"
        else:
            valence = "neutral"

        if a >= 0.6:
            arousal = "high"
        elif a <= 0.3:
            arousal = "low"
        else:
            arousal = "medium"

        label = self._label_from(valence, arousal, f_norm)
        cognitive = self._cognitive_from(valence, arousal)
        motivation = self._motivation_from(valence, arousal, e)
        stability = clamp(0.65 * (1.0 - f_norm) + 0.35 * e, 0.0, 1.0)

        return SemanticFeeling(
            label=label,
            cognitive=cognitive,
            motivation=motivation,
            stability=stability,
        )

    def _label_from(self, valence: str, arousal: str, f_norm: float) -> str:
        if f_norm >= 0.75:
            return "heavy fatigue"
        if valence == "positive" and arousal == "high":
            return "excited optimism"
        if valence == "positive" and arousal == "low":
            return "calm contentment"
        if valence == "neutral" and arousal == "high":
            return "alert curiosity"
        if valence == "neutral" and arousal == "low":
            return "quiet watchfulness"
        if valence == "negative" and arousal == "high":
            return "restless tension"
        if valence == "negative" and arousal == "low":
            return "sad withdrawal"
        return "steady focus"

    def _cognitive_from(self, valence: str, arousal: str) -> str:
        if valence == "negative" and arousal == "high":
            return "strained but alert"
        if valence == "negative" and arousal == "low":
            return "sluggish processing"
        if valence == "positive" and arousal == "high":
            return "fast associative"
        if valence == "positive" and arousal == "low":
            return "settled reflection"
        if arousal == "high":
            return "vigilant scanning"
        if arousal == "low":
            return "low tempo reasoning"
        return "balanced awareness"

    def _motivation_from(self, valence: str, arousal: str, energy: float) -> str:
        if valence == "positive" and arousal == "high":
            return "seeking engagement"
        if valence == "negative" and arousal == "high":
            return "seeking resolution"
        if energy <= 0.3:
            return "seeking rest"
        if valence == "positive":
            return "maintain momentum"
        if valence == "negative":
            return "avoid friction"
        return "steady maintenance"
