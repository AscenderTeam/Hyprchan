from __future__ import annotations

from collections import Counter
from typing import Any

from core.hypraios.kernel.event_compaction.contracts import (
    EventCompacter,
    EventCompactionRequest,
    EventCompactionResult,
)
from core.hypraios.linguistic.inference_engine import InferenceEngine


class GPT5NanoEventCompacter(EventCompacter):
    def __init__(
        self,
        *,
        model: str = "gpt-5-nano",
        max_sentence_chars: int = 220,
        inference_engine: InferenceEngine | None = None,
    ) -> None:
        self.model = str(model or "gpt-5-nano").strip() or "gpt-5-nano"
        self.max_sentence_chars = max(80, int(max_sentence_chars))
        self.inference_engine = inference_engine or InferenceEngine(model=self.model)

    async def compact(
        self, request: EventCompactionRequest
    ) -> EventCompactionResult | None:
        events = [event for event in request.events if isinstance(event, dict)]
        if not events:
            return None

        max_chars = max(80, int(request.max_sentence_chars or self.max_sentence_chars))

        payload = [self._event_payload(event) for event in events]
        messages = [
            {
                "role": "system",
                "content": (
                    "You summarize high-frequency telemetry events into one meaningful sentence. "
                    "Focus on meaningful change only. Ignore repetitive jitter. "
                    f"Return exactly one sentence under {max_chars} characters."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Summarize this event window as one coherent sentence. "
                    "If there is no meaningful change, say that background activity was repetitive.\n\n"
                    f"events={payload}"
                ),
            },
        ]

        try:
            result = await self.inference_engine.infer(
                messages,
                temperature=0.1,
                top_p=1.0,
                max_output_tokens=96,
            )
            summary = self._normalize_sentence(result.output, max_chars=max_chars)
            if not summary:
                summary = self._fallback_summary(events, max_chars=max_chars)
            return EventCompactionResult(
                summary=summary,
                model=str(result.model or self.model),
                compacted_count=len(events),
            )
        except Exception:
            return EventCompactionResult(
                summary=self._fallback_summary(events, max_chars=max_chars),
                model=self.model,
                compacted_count=len(events),
            )

    @staticmethod
    def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": str(event.get("type", "")),
            "origin": str(event.get("origin", "")),
            "description": str(event.get("description", ""))[:180],
            "amplitude": float(event.get("amplitude", 0.0) or 0.0),
        }

    def _fallback_summary(self, events: list[dict[str, Any]], *, max_chars: int) -> str:
        types = Counter(str(event.get("type", "unknown")) for event in events)
        origins = Counter(str(event.get("origin", "unknown")) for event in events)
        top_type = types.most_common(1)[0][0] if types else "background"
        top_origin = origins.most_common(1)[0][0] if origins else "system"
        latest = str(events[-1].get("description", "")).strip()
        if latest:
            base = f"Background activity was mostly {top_type} from {top_origin}; latest change was {latest}."
        else:
            base = f"Background activity was mostly repetitive {top_type} signals from {top_origin}."
        return self._normalize_sentence(base, max_chars=max_chars)

    @staticmethod
    def _normalize_sentence(text: str, *, max_chars: int) -> str:
        compact = " ".join(str(text or "").replace("\n", " ").split()).strip()
        if not compact:
            return ""

        split_pos = len(compact)
        for punct in (". ", "! ", "? "):
            idx = compact.find(punct)
            if idx != -1:
                split_pos = min(split_pos, idx + 1)
        compact = compact[:split_pos].strip()

        if len(compact) > max_chars:
            compact = compact[: max_chars - 1].rstrip(" ,;:")
        if compact and compact[-1] not in ".!?":
            compact += "."
        return compact
