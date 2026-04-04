from collections import defaultdict
from typing import Any


SYSTEM_INTRO_MESSAGE = (
    "<system>Passive cognition channel active. Signals here are private internal context, "
    "not direct user dialogue.</system>"
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
        grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "weight": 0.0,
                "sample_description": "",
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
            grouped[key]["sample_description"] = description

        lines: list[str] = []
        if self.include_system_intro:
            lines.append(SYSTEM_INTRO_MESSAGE)
            lines.append(
                "<system>Passive mode note: think first, act intentionally, and communicate only when you decide to.</system>"
            )

        if not grouped and unknown_count == 0:
            lines.append("No meaningful passive triggers detected right now.")
            lines.append("Keep a quiet internal checkpoint and wait for a better signal.")
            self._cached_prompt = "\n".join(lines)
            return self._cached_prompt

        sorted_groups = sorted(
            grouped.items(),
            key=lambda entry: entry[1]["weight"],
            reverse=True,
        )

        lead_templates = [
            "Passive cognition cues:",
            "Internal attention points:",
            "Background reasoning context:",
            "Autonomy decision window:",
        ]
        lines.append(lead_templates[inference_count % len(lead_templates)])

        for (input_type, _origin), data in sorted_groups[:8]:
            origin = str(data["origin"]).strip() or "unknown"
            count = data["count"]
            description = str(data["sample_description"]).strip()
            label = input_type.replace("_", " ").strip() or "signal"
            if description:
                if count > 1:
                    lines.append(
                        f"- {label}: {description} (pattern repeated {count} times from {origin})"
                    )
                else:
                    lines.append(f"- {label}: {description} (from {origin})")
            else:
                lines.append(f"- {label}: sensed from {origin}")

        if unknown_count > 0:
            lines.append("- Some low-fidelity signals were ignored.")

        lines.append(
            "Think privately first. If action is useful, you may call tools."
        )
        lines.append(
            "Do not produce user-visible text unless you intentionally choose a communication path."
        )
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
