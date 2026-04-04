from __future__ import annotations

from dataclasses import dataclass

from core.hyprmemory.utils.math import clamp


@dataclass(slots=True)
class WeightedSalienceJudge:
    """Compute salience for STM items and episodes.

    Implements a simplified salience rule from memory hierarchy work (MemGPT,
    arXiv:2310.08560) and episodic distillation (REMem, arXiv:2503.15869).
    """

    w_novelty: float = 0.35
    w_goal: float = 0.25
    w_emotion: float = 0.25
    w_user: float = 0.15

    def score(
        self,
        *,
        novelty: float,
        goal_rel: float,
        emotion_intensity: float,
        user_importance: float,
    ) -> float:
        value = (
            self.w_novelty * novelty
            + self.w_goal * goal_rel
            + self.w_emotion * emotion_intensity
            + self.w_user * user_importance
        )
        return clamp(value, 0.0, 1.0)
