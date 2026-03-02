from typing import Any
from collections import defaultdict


SYSTEM_INTRO_MESSAGE = (
    "<system>Hello Hypr-chan! Nice to meet you for the first. I'm your nervous system, "
    "made to keep you up to date about your internal states, if you think you can talk to me, "
    "you're silly he-he. You can't. I'm not alive either I don't have intelligence to respond, "
    "I'm just an informer that lets you know, one side only!</system>"
)


class PassiveProcessor:
    def __init__(
        self,
        inputs: list[dict[str, Any]],
        *,
        include_system_intro: bool = False,
    ) -> None:
        self.inputs = inputs
        self.include_system_intro = include_system_intro
        self._cached_prompt: str | None = None

    async def process_inputs(self, inference_count: int):
        """
        Processes all inputs, that are related to system and hyprland-interface.
        If inputs don't satisfy the format requirement, then they are skipped or passed as "received unknown input, something bothers you." depending on intensity that should ALL inputs define.
        If unknown type of inputs (those that don't match the required format) are present, accumulate them and if there is majority of them, then make one single system message telling Hypr-chan that something serious bothering her system.
        Sort same type of inputs into one depending on balance of amount, if there's a lot of same inputs in sequence, the priority is more!
        System messages shouldn't be same-same text, diversification of messages (e.g. "There's X happening" to "X happening in you" matters!)

        Input required formats:
        {
            "type": string, // type of input (if not present, it's unknwon type of input!)
            "amplitude": float, // the quality and amplitude level of the input, higher - prior.
            "description": string, // Mandatory description of input
            "origin": string // Where this input is coming from
        }

        Args:
            inference_count (int): Amount of inference that happened
        """
        grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "weight": 0.0,
                "description": "",
                "origin": "",
                "count": 0,
            }
        )
        unknown_count = 0

        for item in self.inputs:
            if not isinstance(item, dict):
                unknown_count += 1
                continue

            input_type = item.get("type")
            description = item.get("description")
            origin = item.get("origin")
            amplitude = item.get("amplitude")

            if (
                not isinstance(input_type, str)
                or not isinstance(description, str)
                or not isinstance(origin, str)
            ):
                unknown_count += 1
                continue

            try:
                if not isinstance(amplitude, (int, float, str)):
                    raise ValueError("Invalid amplitude type")
                amp = max(0.0, float(amplitude))
            except (TypeError, ValueError):
                unknown_count += 1
                continue

            key = (input_type, origin)
            grouped[key]["weight"] += amp
            grouped[key]["count"] += 1
            grouped[key]["origin"] = origin
            grouped[key]["description"] = description

        lines: list[str] = []
        if self.include_system_intro:
            lines.append(SYSTEM_INTRO_MESSAGE)
            lines.append(
                "<system>Protocol note: SYSTEM is one-way telemetry only. Do not address SYSTEM directly.</system>"
            )

        if not grouped and unknown_count == 0:
            lines.append("No passive events are currently queued.")
            lines.append("Respond with concise self-observation only.")
            self._cached_prompt = "\n".join(lines)
            return self._cached_prompt

        sorted_groups = sorted(
            grouped.items(),
            key=lambda entry: entry[1]["weight"],
            reverse=True,
        )

        lead_templates = [
            "System telemetry update:",
            "New internal signals detected:",
            "Body and interface status report:",
            "Passive signal digest:",
        ]
        lines.append(lead_templates[inference_count % len(lead_templates)])

        for (input_type, _origin), data in sorted_groups[:8]:
            weight = data["weight"]
            count = data["count"]
            description = data["description"]
            lines.append(
                f"- type={input_type} count={count} weight={weight:.2f}: {description}"
            )

        total_items = len(self.inputs)
        if unknown_count > 0 and unknown_count >= max(1, total_items // 2):
            lines.append(
                "- warning: significant unknown passive input formats were detected"
            )

        lines.append("Respond with concise self-observation only.")
        self._cached_prompt = "\n".join(lines)
        return self._cached_prompt

    async def inference_invoke(self):
        """
        Invoke LM Inference after given processing inputs.
        NOTE: Execute this function, ONLY after `process_inputs(...)`
        """
        if self._cached_prompt is None:
            raise RuntimeError(
                "process_inputs(...) must be called before inference_invoke()"
            )
        return self._cached_prompt
