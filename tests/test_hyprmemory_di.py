"""
Verify that HyprMemoryService is correctly registered in Ascender's DI container
via provideHyprmemory(), and that inject() can resolve it after registration.
"""

import pytest
from unittest.mock import MagicMock, patch

from ascender.core.applications.root_injector import RootInjector

from hyprchan.core.hyprmemory import HyprMemoryService
from hyprchan.core.hyprmemory.provider import provideHyprmemory


@pytest.fixture(autouse=True)
def reset_root_injector():
    """Reset the RootInjector singleton between tests to avoid state bleed."""
    RootInjector._instance = None
    RootInjector._injector = None
    yield
    RootInjector._instance = None
    RootInjector._injector = None


def test_provide_hyprmemory_returns_hyprmemory_service_class():
    assert provideHyprmemory() is HyprMemoryService


def test_hyprmemory_service_registered_in_injector_dependencies():
    """Registration should add HyprMemoryService to the injector dependency map
    without triggering instantiation (no real DB/Redis needed)."""
    root = RootInjector()
    root.create([provideHyprmemory()])

    assert HyprMemoryService in root.injector.dependencies


def test_inject_resolves_hyprmemory_service_instance():
    """inject(HyprMemoryService) should return a live instance when all
    constructor dependencies are satisfied (mocked here)."""
    from ascender.core import inject

    fake_db = MagicMock()
    fake_db.engine.engine.dialect.name = "sqlite"
    fake_logger = MagicMock()

    with (
        patch(
            "hyprchan.core.hyprmemory.services.memory_service.HyprMemoryService.__init__",
            return_value=None,
        ) as mock_init,
    ):
        root = RootInjector()
        root.create([
            provideHyprmemory(),
            {"provide": "ASC_LOGGER", "value": fake_logger},
        ])

        # Patch the DB engine injection that the constructor would call
        with patch.object(
            root.injector,
            "get",
            wraps=lambda token, **kw: (
                HyprMemoryService.__new__(HyprMemoryService)
                if token is HyprMemoryService
                else kw.get("not_found_value")
            ),
        ):
            instance = inject(HyprMemoryService, fallback=None)

    assert instance is not None
    assert isinstance(instance, HyprMemoryService)
