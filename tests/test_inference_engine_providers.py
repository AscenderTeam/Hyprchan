import pytest

from core.hypraios.linguistic.inference_engine import InferenceEngine


def test_resolve_target_parses_provider_and_model() -> None:
    target = InferenceEngine._resolve_target(
        raw_target="gemini:gemini-2.5-flash",
        explicit_model=None,
    )
    assert target.provider == "gemini"
    assert target.model == "gemini-2.5-flash"


def test_resolve_target_uses_openai_for_legacy_model_only_format() -> None:
    target = InferenceEngine._resolve_target(
        raw_target="gpt-4o-mini",
        explicit_model=None,
    )
    assert target.provider == "openai"
    assert target.model == "gpt-4o-mini"


def test_resolve_target_applies_provider_aliases() -> None:
    target = InferenceEngine._resolve_target(
        raw_target="google:gemini-2.5-flash",
        explicit_model=None,
    )
    assert target.provider == "gemini"
    assert target.model == "gemini-2.5-flash"


def test_resolve_target_explicit_model_overrides_target_model() -> None:
    target = InferenceEngine._resolve_target(
        raw_target="openrouter:meta-llama/llama-3.3-70b-instruct",
        explicit_model="openai/gpt-5-nano",
    )
    assert target.provider == "openrouter"
    assert target.model == "openai/gpt-5-nano"


def test_inference_engine_normalizes_openai_prefixed_model() -> None:
    engine = InferenceEngine(inference_target="openai:openai/gpt-4o-mini")
    assert engine.provider_name == "openai"
    assert engine.model == "gpt-4o-mini"


def test_inference_engine_supports_openrouter_target() -> None:
    engine = InferenceEngine(
        inference_target="openrouter:anthropic/claude-3.5-sonnet",
    )
    assert engine.provider_name == "openrouter"
    assert engine.model == "anthropic/claude-3.5-sonnet"


def test_inference_engine_rejects_unknown_provider() -> None:
    with pytest.raises(RuntimeError):
        InferenceEngine(inference_target="unknown:model")
