import re
from typing import Literal

from hyprchan.core.hypraios.constants import Phases
from hyprchan.core.hypraios.kernel.states import KernelStates


class PhaseEngine:
    def __init__(self, kernel_states: KernelStates) -> None:
        self.kernel_states = kernel_states
        self.CONTROL_TAG_RE = re.compile(
            r"<control\b[^>]*>(.*?)</control>", re.IGNORECASE | re.DOTALL
        )
        self._token_re = re.compile(r"[a-z']+")

        self.v0 = 0.35
        self.k_v = 0.07
        self.alpha_r = 0.25
        self.alpha_p = 0.2

        self.lambda_r = 0.9
        self.r_max = 1.0
        self.r = 0.0
        self.r_angry_threshold = 0.6

        self.k_e = 0.08
        self.e0 = 0.55
        self.beta_a = 0.2
        self.beta_f = 0.45

        self.last_delta = 0.0
        self.active_reason: Literal["USER", "SELF"] = "SELF"

        self.positive_lexicon = {
            "thanks",
            "thank",
            "great",
            "good",
            "nice",
            "love",
            "cool",
            "helpful",
            "awesome",
            "sweet",
        }
        self.negative_lexicon = {
            "stupid",
            "idiot",
            "hate",
            "useless",
            "dumb",
            "trash",
            "awful",
            "annoying",
            "shut",
            "bad",
        }

    @staticmethod
    def _clamp(value: float, lo: float, hi: float):
        return max(lo, min(hi, value))

    def _lexicon_score(self, text: str) -> float:
        if not text:
            return 0.0
        tokens = self._token_re.findall(text.lower())
        if not tokens:
            return 0.0

        pos = sum(1 for token in tokens if token in self.positive_lexicon)
        neg = sum(1 for token in tokens if token in self.negative_lexicon)
        return (pos - neg) / max(1, len(tokens))

    async def process_interaction_delta(self, output: str, input: str):
        # Convert input and output embedding tokens into scalar delta value.
        # Which will be used for ining
        u = self._lexicon_score(input)
        v = self._lexicon_score(output)
        delta = u - v
        self.last_delta = delta
        return delta

    async def handle_commands(self, text: str):
        commands = self.CONTROL_TAG_RE.findall(text or "")
        if not commands:
            return text

        for command in commands:
            normalized = command.strip().lower()

            if "sleep" in normalized:
                self.kernel_states.phase = Phases.SLEEP
                continue
            if "maint" in normalized:
                self.kernel_states.phase = Phases.MAINT
                continue
            if "passive" in normalized:
                self.kernel_states.phase = Phases.PASSIVE
                continue
            if "active" in normalized:
                self.kernel_states.phase = Phases.ACTIVE
                self.active_reason = "USER" if "user" in normalized else "SELF"

        return self.CONTROL_TAG_RE.sub("", text).strip()

    def project_mood(self) -> str:
        e = self.kernel_states.e.value
        v = self.kernel_states.v.value

        if v < -0.6 and self.r > self.r_angry_threshold:
            return "angry"
        if v < -0.25:
            return "irritated"
        if e > 0.75 and v > 0.2:
            return "sparkly"
        if e > 0.55 and v > 0.1:
            return "cheerful"
        if abs(v) <= 0.1:
            return "neutral"
        return "steady"

    def reset_after_sleep(self):
        self.kernel_states.e.value = 0.9
        self.kernel_states.v.value = self._clamp(self.v0 + 0.08, -1.0, 1.0)
        self.kernel_states.a.value = 0.25
        self.r = 0.0

    async def after_inference(self, input: str, output: str):
        """
        Fired after each inference

        Args:
            output (str): Given LLM's output that may contain specific control tags.
            input (str): If state is active, user input is given here, sometimes also system inputs as well. If no priority system inputs given, then previous output used.
        """
        cleaned_output = await self.handle_commands(output)
        d = await self.process_interaction_delta(cleaned_output, input)

        neg_d = self._clamp(-d, 0.0, self.r_max)
        pos_d = self._clamp(d, 0.0, 1.0)

        self.r = self.lambda_r * self.r + (1 - self.lambda_r) * neg_d

        self.kernel_states.v.value = (
            self.kernel_states.v.value
            + self.k_v * (self.v0 - self.kernel_states.v.value)
            - self.alpha_r * self.r
            + self.alpha_p * pos_d
        )

        self.kernel_states.a.value = self._clamp(
            (self.kernel_states.a.value * 0.8) + (0.2 * (abs(d) + self.r)),
            0.0,
            1.0,
        )

        f_ratio = self._clamp(
            self.kernel_states.f.value / max(self.kernel_states.f.max_val, 1e-6),
            0.0,
            1.0,
        )
        self.kernel_states.e.value = self._clamp(
            self.kernel_states.e.value
            + self.k_e * (self.e0 - self.kernel_states.e.value)
            + self.beta_a * self.kernel_states.a.value
            - self.beta_f * f_ratio,
            0.0,
            1.0,
        )

        return {
            "output": cleaned_output,
            "delta": d,
            "rudeness": self.r,
            "mood": self.project_mood(),
            "active_reason": self.active_reason,
        }
