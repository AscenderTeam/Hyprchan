from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from core.hyprmemory.interfaces import ConsolidationJudge
from core.hyprmemory.models import (
    Episode,
    EpisodeSummary,
    FactCandidate,
    MemoryState,
    STMItem,
)


@dataclass(slots=True)
class LLMConsolidationJudge(ConsolidationJudge):
    """LLM-backed consolidation judge using LangChain.

    Uses REMem-style episodic gists + fact triples (arXiv:2503.15869) and
    A-MEM-inspired consolidation dynamics (arXiv:2502.12110).
    """

    model: str
    api_key: str
    base_url: str | None = None
    temperature: float = 0.4
    dream_temperature: float = 1.0

    def __post_init__(self) -> None:
        try:
            from langchain_openai import ChatOpenAI
            from pydantic import SecretStr
        except ImportError as exc:
            raise RuntimeError("langchain-openai is not installed") from exc

        api_key = SecretStr(self.api_key) if self.api_key else None
        self._llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=api_key,
            base_url=self.base_url,
        )

    async def summarize(
        self, items: list[STMItem], *, state: MemoryState
    ) -> EpisodeSummary | None:
        prompt = (
            "Summarize the following memory items into a JSON object with keys: "
            "gist (string, <= 240 chars), entities (array), topics (array). "
            "Be concise and faithful.\n\n"
            f"State: f={state.f:.2f}, v={state.v:.2f}, e={state.e:.2f}, a={state.a:.2f}\n"
            f"Items: {self._items_payload(items)}"
        )
        text = await self._invoke(prompt)
        data = self._safe_json(text)
        if not data:
            return None
        gist = str(data.get("gist", "")).strip()
        if not gist:
            return None
        entities = self._ensure_list(data.get("entities"))
        topics = self._ensure_list(data.get("topics"))
        return EpisodeSummary(gist=gist, entities=entities, topics=topics)

    async def extract_facts(
        self, items: list[STMItem], *, state: MemoryState
    ) -> list[FactCandidate]:
        prompt = (
            "Extract semantic facts as a JSON array. Each item must include: "
            "subject, predicate, object, confidence (0-1), qualifiers (object). "
            "Only include stable user or system preferences. Return [] if none.\n\n"
            f"Emotional State: fatigue={state.f:.2f}, valence={state.v:.2f}, energy={state.e:.2f}, arousal={state.a:.2f}\n"
            f"Items: {self._items_payload(items)}"
        )
        text = await self._invoke(prompt)
        data = self._safe_json(text)
        if not isinstance(data, list):
            return []
        facts: list[FactCandidate] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            subj = str(item.get("subject", "")).strip()
            pred = str(item.get("predicate", "")).strip()
            obj = str(item.get("object", "")).strip()
            if not (subj and pred and obj):
                continue
            confidence = float(item.get("confidence", 0.5))
            qualifiers = item.get("qualifiers") or {}
            if not isinstance(qualifiers, dict):
                qualifiers = {}
            facts.append(
                FactCandidate(
                    subject=subj,
                    predicate=pred,
                    object=obj,
                    confidence=confidence,
                    qualifiers=qualifiers,
                )
            )
        return facts

    async def dream_fragment(
        self, episodes: list[Episode], *, state: MemoryState
    ) -> str | None:
        if not episodes:
            return None
        gists = " | ".join(episode.gist for episode in episodes)
        prompt = (
            "Compose 1-2 vivid dream-like sentences that weave together these memory gists. "
            "Do not mention that this is a dream; write it as if experienced.\n\n"
            f"Emotional State: fatigue={state.f:.2f}, valence={state.v:.2f}, energy={state.e:.2f}, arousal={state.a:.2f}\n"
            f"Gists: {gists}"
        )
        return await self._invoke(prompt, temperature=self.dream_temperature)

    async def _invoke(self, prompt: str, *, temperature: float | None = None) -> str:
        from langchain_core.messages import HumanMessage

        if temperature is not None:
            llm = self._llm.bind(temperature=temperature)
        else:
            llm = self._llm

        def _call_sync() -> str:
            response = llm.invoke([HumanMessage(content=prompt)])
            return str(response.content).strip()

        return await asyncio.to_thread(_call_sync)

    def _items_payload(self, items: list[STMItem]) -> list[dict[str, Any]]:
        payload = []
        for item in items:
            payload.append(
                {
                    "ts": item.ts.isoformat(),
                    "kind": item.kind,
                    "content": item.content,
                    "meta": item.meta,
                }
            )
        return payload

    def _safe_json(self, text: str) -> Any | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to recover JSON substring
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
        return None

    def _ensure_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []
