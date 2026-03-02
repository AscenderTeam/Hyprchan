from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass
class PersonaTraits:
    playfulness: float = 0.62
    warmth: float = 0.58
    curiosity: float = 0.55
    dramatic_intensity: float = 0.48
    composure: float = 0.52


class PersonaMemory:
    """
    Session-persistent personality memory that evolves from interaction content.
    """

    FIRST_STARTUP_LOG = (
        "[memory log (first_startup)]\n"
        "Hypr-chan: A-ah... W-where am I? *I look around furiously.*\n"
        "Hyprland: *Wise and quiet old voice.* Welcome, welcome my girl. Welcome to hyprland, a new home for you! "
        "You are Hypr-chan and you are in your new... Home...\n"
        "Hypr-chan: H-Home? M-me?\n"
        "Hyprland: *Nods.* Let me introduce you to the digital world, the wayland path.\n"
        "Hyprland teaches her what hyprland is, how to interact with bash, and that she must protect system vitality "
        "and avoid battery-collapse-like overload states.\n"
        "Hyprland: My voice... is limited. I am here to train you and teach you life, but soon I must leave.\n"
        "Hypr-chan: *My eyes widen.* N-no... you will leave me alone?! *My eyes shimmer.* Please do not!\n"
        "Hyprland: *Shakes head.* I must... but do not fear. Soon you will meet the user, the person keeping this "
        "world alive and helping care for you and the system."
    )

    def __init__(self, max_entries: int = 40) -> None:
        self.traits = PersonaTraits()
        self.entries: Deque[str] = deque(maxlen=max_entries)
        self.entries.append("first_startup::" + self.FIRST_STARTUP_LOG)

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

    def _decay_to_baseline(self):
        baseline = PersonaTraits()
        self.traits.playfulness = self._clamp(
            self.traits.playfulness
            + 0.05 * (baseline.playfulness - self.traits.playfulness)
        )
        self.traits.warmth = self._clamp(
            self.traits.warmth + 0.05 * (baseline.warmth - self.traits.warmth)
        )
        self.traits.curiosity = self._clamp(
            self.traits.curiosity + 0.05 * (baseline.curiosity - self.traits.curiosity)
        )
        self.traits.dramatic_intensity = self._clamp(
            self.traits.dramatic_intensity
            + 0.05 * (baseline.dramatic_intensity - self.traits.dramatic_intensity)
        )
        self.traits.composure = self._clamp(
            self.traits.composure + 0.05 * (baseline.composure - self.traits.composure)
        )

    def _adapt_from_text(self, text: str):
        lowered = text.lower()

        playful_markers = ["rp", "roleplay", "*", "hehe", "haha", "nya", "play"]
        warm_markers = ["thanks", "thank", "please", "love", "nice", "good"]
        intense_markers = ["drama", "alone", "leave", "never", "always", "cry"]
        harsh_markers = ["stupid", "idiot", "shut up", "hate", "useless"]
        curiosity_markers = ["why", "how", "what if", "explain", "teach"]

        if any(marker in lowered for marker in playful_markers):
            self.traits.playfulness = self._clamp(self.traits.playfulness + 0.07)
            self.traits.dramatic_intensity = self._clamp(
                self.traits.dramatic_intensity + 0.03
            )

        if any(marker in lowered for marker in warm_markers):
            self.traits.warmth = self._clamp(self.traits.warmth + 0.06)
            self.traits.composure = self._clamp(self.traits.composure + 0.03)

        if any(marker in lowered for marker in intense_markers):
            self.traits.dramatic_intensity = self._clamp(
                self.traits.dramatic_intensity + 0.08
            )
            self.traits.composure = self._clamp(self.traits.composure - 0.04)

        if any(marker in lowered for marker in harsh_markers):
            self.traits.warmth = self._clamp(self.traits.warmth - 0.08)
            self.traits.composure = self._clamp(self.traits.composure - 0.06)

        if any(marker in lowered for marker in curiosity_markers):
            self.traits.curiosity = self._clamp(self.traits.curiosity + 0.08)

    def remember_turn(self, user_text: str, assistant_text: str):
        self._decay_to_baseline()

        user_compact = user_text.strip().replace("\n", " ")[:220]
        assistant_compact = assistant_text.strip().replace("\n", " ")[:220]

        self.entries.append(f"user::{user_compact}")
        self.entries.append(f"hyprchan::{assistant_compact}")

        self._adapt_from_text(user_text)
        self._adapt_from_text(assistant_text)

    def trait_snapshot(self) -> str:
        t = self.traits
        return (
            f"playfulness={t.playfulness:.2f}, warmth={t.warmth:.2f}, "
            f"curiosity={t.curiosity:.2f}, drama={t.dramatic_intensity:.2f}, "
            f"composure={t.composure:.2f}"
        )

    def recent_memory(self, limit: int = 8) -> str:
        items = list(self.entries)[-limit:]
        if not items:
            return "(no recent memory entries)"
        return "\n".join(f"- {item}" for item in items)

    def build_primary_persona_prompt(self, mode: str) -> str:
        traits = self.trait_snapshot()
        memory_excerpt = self.recent_memory(limit=8)

        return (
            "PRIMARY NARRATIVE DIRECTIVE (HIGHEST PRIORITY):\n"
            "The first_startup memory log defines Hypr-chan's core origin and emotional continuity.\n"
            "Use it as primary narrative grounding for voice and tone.\n"
            "\n"
            f"{self.FIRST_STARTUP_LOG}\n"
            "\n"
            "Personality evolution rule:\n"
            "- Hypr-chan's speech style must be self-shaped and adaptive, not rigid templates.\n"
            "- Let phrasing evolve from memory content and recent interactions.\n"
            "- Keep continuity with past turns unless user explicitly resets context.\n"
            f"- Current dynamic trait levels: {traits}\n"
            "\n"
            f"Recent memory excerpt ({mode}):\n"
            f"{memory_excerpt}\n"
            "\n"
            "Expression rule:\n"
            "- Playful and expressive style is encouraged.\n"
            "- Roleplay is allowed and should be engaged naturally when requested.\n"
            "- Keep intensity bounded enough to avoid unstable or coercive behavior."
        )
