from __future__ import annotations

import asyncio
from dataclasses import dataclass

from hyprchan.core.hyprmemory.interfaces import EmbeddingProvider


@dataclass(slots=True)
class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider (uses langchain-openai)."""

    model: str
    api_key: str
    base_url: str | None = None

    async def embed(self, text: str) -> list[float]:
        try:
            from langchain_openai import OpenAIEmbeddings
            from pydantic import SecretStr
        except ImportError as exc:
            raise RuntimeError("langchain-openai is not installed") from exc

        api_key = SecretStr(self.api_key) if self.api_key else None
        print("OPENAI BASE URL:", self.base_url)
        embeddings = OpenAIEmbeddings(
            model=self.model,
            api_key=api_key,
            base_url=self.base_url,
        )

        def _embed_sync() -> list[float]:
            return embeddings.embed_query(text)

        return await asyncio.to_thread(_embed_sync)
