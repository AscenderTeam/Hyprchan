from importlib import import_module
from typing import Any

from hyprchan.core.hyprmemory.services.retriever import HybridRetriever


def _resolve_hyprmemory_service() -> Any:
    try:
        module = import_module("core.hyprmemory.services.memory_service")
        return getattr(module, "HyprMemoryService")
    except Exception:

        class _UnavailableHyprMemoryService:
            pass

        return _UnavailableHyprMemoryService


HyprMemoryService: Any = _resolve_hyprmemory_service()

__all__ = ["HyprMemoryService", "HybridRetriever"]
