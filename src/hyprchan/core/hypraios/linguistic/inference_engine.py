import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from settings import (
    GEMINI_API_BASE_URL,
    GEMINI_API_KEY,
    INFERENCE_TARGET,
    OPENAI_API_BASE_URL,
    OPENAI_MODEL,
    OPENAI_OAUTH_TOKEN,
    OPENAI_TIMEOUT_SECONDS,
    OPENROUTER_API_BASE_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_HTTP_REFERER,
    OPENROUTER_X_TITLE,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InferenceResult:
    output: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    tool_calls: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass(slots=True)
class InferenceRequest:
    model: str
    messages: list[dict[str, Any]]
    temperature: float
    top_p: float | None
    max_output_tokens: int
    logit_bias: dict[str, int] | None
    frequency_penalty: float | None
    presence_penalty: float | None
    tools: list[Any] | None


@dataclass(slots=True)
class InferenceTargetConfig:
    provider: str
    model: str


class InferenceProvider(Protocol):
    async def inference(self, request: InferenceRequest) -> InferenceResult: ...


class BaseChatInferenceProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str,
        base_url: str,
        timeout_sec: float,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.api_key = str(api_key or "")
        self.base_url = _normalize_api_base_url(base_url)
        self.timeout_sec = max(1.0, float(timeout_sec))
        self.default_headers = dict(default_headers or {})

    async def inference(self, request: InferenceRequest) -> InferenceResult:
        token = self._require_api_key()
        lc_messages = self._to_langchain_messages(request.messages)
        model_kwargs: dict[str, Any] = {}
        if request.logit_bias:
            model_kwargs["logit_bias"] = request.logit_bias
        if request.frequency_penalty is not None:
            model_kwargs["frequency_penalty"] = float(request.frequency_penalty)
        if request.presence_penalty is not None:
            model_kwargs["presence_penalty"] = float(request.presence_penalty)

        chat_kwargs: dict[str, Any] = {
            "model": request.model,
            "api_key": SecretStr(token),
            "base_url": self.base_url,
            "timeout": self.timeout_sec,
            "temperature": float(request.temperature),
            "max_tokens": max(64, int(request.max_output_tokens)),
        }
        if request.top_p is not None:
            chat_kwargs["top_p"] = float(request.top_p)
        if model_kwargs:
            chat_kwargs["model_kwargs"] = model_kwargs
        if self.default_headers:
            chat_kwargs["default_headers"] = dict(self.default_headers)

        llm = ChatOpenAI(**chat_kwargs)
        if request.tools:
            llm = llm.bind_tools(request.tools)

        logger.debug(
            "Invoking provider=%s model=%s top_p=%s tools=%s",
            self.provider_name,
            request.model,
            request.top_p is not None,
            len(request.tools or []),
        )
        response = await llm.ainvoke(lc_messages)  # pyright: ignore[reportReturnType]

        tool_calls = self._extract_tool_calls(response)
        output = self._extract_output(response, allow_empty=bool(tool_calls))
        input_tokens, output_tokens, total_tokens = self._extract_usage(response)

        return InferenceResult(
            output=output,
            model=self._extract_model(response, fallback=request.model),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            tool_calls=tool_calls,
            raw=self._extract_raw(response),
        )

    def _require_api_key(self) -> str:
        token = str(self.api_key or "").strip()
        if token and not token.startswith("your_"):
            return token
        raise RuntimeError(
            f"Missing API token for provider '{self.provider_name}'. "
            "Set the corresponding provider key in environment variables."
        )

    @staticmethod
    def _to_langchain_messages(messages: list[dict[str, Any]]) -> list[BaseMessage]:
        out: list[BaseMessage] = []
        for message in messages:
            if not isinstance(message, dict):
                continue

            role = str(message.get("role", "user")).strip().lower()
            raw_content = message.get("content", "")
            content: Any
            if isinstance(raw_content, list):
                content = raw_content
            else:
                content = str(raw_content)

            if role == "system":
                out.append(SystemMessage(content=content))
            elif role == "assistant":
                out.append(AIMessage(content=content))
            else:
                out.append(HumanMessage(content=content))

        if not out:
            out.append(HumanMessage(content=""))
        return out

    @staticmethod
    def _extract_output(response: Any, *, allow_empty: bool = False) -> str:
        content = getattr(response, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()

        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                    continue
                if isinstance(item, dict):
                    text_val = item.get("text")
                    if isinstance(text_val, str):
                        chunks.append(text_val)
            merged = "\n".join(
                chunk.strip() for chunk in chunks if chunk.strip()
            ).strip()
            if merged:
                return merged

        if allow_empty:
            return ""
        raise RuntimeError("LLM response did not include textual output")

    @staticmethod
    def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        direct_calls = getattr(response, "tool_calls", None)
        if isinstance(direct_calls, list):
            for call in direct_calls:
                if not isinstance(call, dict):
                    continue
                name = str(call.get("name", "")).strip()
                args = BaseChatInferenceProvider._parse_tool_args(call.get("args"))
                if not name:
                    continue
                normalized.append({"name": name, "args": args})
            if normalized:
                return normalized

        # Some providers expose OpenAI-style function calls via additional_kwargs.
        additional_kwargs = getattr(response, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict):
            raw_calls = additional_kwargs.get("tool_calls")
            if isinstance(raw_calls, list):
                for call in raw_calls:
                    if not isinstance(call, dict):
                        continue
                    function_payload = call.get("function")
                    if not isinstance(function_payload, dict):
                        continue
                    name = str(function_payload.get("name", "")).strip()
                    args = BaseChatInferenceProvider._parse_tool_args(
                        function_payload.get("arguments")
                    )
                    if not name:
                        continue
                    normalized.append({"name": name, "args": args})

            # Legacy OpenAI-compatible single function call shape.
            single_function = additional_kwargs.get("function_call")
            if isinstance(single_function, dict):
                name = str(single_function.get("name", "")).strip()
                args = BaseChatInferenceProvider._parse_tool_args(
                    single_function.get("arguments")
                )
                if name:
                    normalized.append({"name": name, "args": args})
            if normalized:
                return normalized

        # Some providers emit tool calls as structured content blocks.
        content = getattr(response, "content", None)
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                block_type = str(item.get("type", "")).strip().lower()
                if block_type in {"tool_use", "tool_call"}:
                    name = str(item.get("name", "")).strip()
                    args = BaseChatInferenceProvider._parse_tool_args(item.get("input"))
                    if name:
                        normalized.append({"name": name, "args": args})
                    continue
                if block_type in {"function_call", "function"}:
                    name = str(item.get("name", "")).strip()
                    args = BaseChatInferenceProvider._parse_tool_args(
                        item.get("arguments")
                    )
                    if name:
                        normalized.append({"name": name, "args": args})
        return normalized

    @staticmethod
    def _parse_tool_args(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
            except Exception:
                return {}
            if isinstance(parsed, dict):
                return parsed
        return {}

    @staticmethod
    def _extract_usage(response: Any) -> tuple[int, int, int]:
        usage_meta = getattr(response, "usage_metadata", None)
        if isinstance(usage_meta, dict):
            input_tokens = int(usage_meta.get("input_tokens", 0) or 0)
            output_tokens = int(usage_meta.get("output_tokens", 0) or 0)
            total_tokens = int(
                usage_meta.get("total_tokens", input_tokens + output_tokens) or 0
            )
            return (input_tokens, output_tokens, total_tokens)

        response_meta = getattr(response, "response_metadata", None)
        if isinstance(response_meta, dict):
            token_usage = response_meta.get("token_usage", {})
            if isinstance(token_usage, dict):
                input_tokens = int(token_usage.get("prompt_tokens", 0) or 0)
                output_tokens = int(token_usage.get("completion_tokens", 0) or 0)
                total_tokens = int(
                    token_usage.get("total_tokens", input_tokens + output_tokens) or 0
                )
                return (input_tokens, output_tokens, total_tokens)

        return (0, 0, 0)

    @staticmethod
    def _extract_model(response: Any, *, fallback: str) -> str:
        response_meta = getattr(response, "response_metadata", None)
        if isinstance(response_meta, dict):
            model_name = response_meta.get("model_name") or response_meta.get("model")
            if isinstance(model_name, str) and model_name.strip():
                return model_name.strip()
        return fallback

    @staticmethod
    def _extract_raw(response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            dumped = response.model_dump()
            if isinstance(dumped, dict):
                return dumped
        if hasattr(response, "dict"):
            dumped = response.dict()
            if isinstance(dumped, dict):
                return dumped
        return {"repr": repr(response)}


class OpenAIInferenceProvider(BaseChatInferenceProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_sec: float,
    ) -> None:
        super().__init__(
            provider_name="openai",
            api_key=api_key
            or OPENAI_OAUTH_TOKEN
            or os.getenv("OPENAI_OAUTH_TOKEN")
            or os.getenv("OPENAI_API_KEY", ""),
            base_url=base_url or OPENAI_API_BASE_URL or "https://api.openai.com/v1",
            timeout_sec=timeout_sec,
        )


class GeminiInferenceProvider(BaseChatInferenceProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_sec: float,
    ) -> None:
        super().__init__(
            provider_name="gemini",
            api_key=api_key
            or GEMINI_API_KEY
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY", ""),
            base_url=base_url
            or GEMINI_API_BASE_URL
            or "https://generativelanguage.googleapis.com/v1beta/openai",
            timeout_sec=timeout_sec,
        )


class OpenRouterInferenceProvider(BaseChatInferenceProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_sec: float,
    ) -> None:
        headers: dict[str, str] = {}
        referer = str(
            OPENROUTER_HTTP_REFERER or os.getenv("OPENROUTER_HTTP_REFERER", "")
        ).strip()
        title = str(OPENROUTER_X_TITLE or os.getenv("OPENROUTER_X_TITLE", "")).strip()
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-Title"] = title

        super().__init__(
            provider_name="openrouter",
            api_key=api_key
            or OPENROUTER_API_KEY
            or os.getenv("OPENROUTER_API_KEY", ""),
            base_url=base_url
            or OPENROUTER_API_BASE_URL
            or "https://openrouter.ai/api/v1",
            timeout_sec=timeout_sec,
            default_headers=headers,
        )


class InferenceEngine:
    """Provider-agnostic inference facade with a narrow provider contract."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_base_url: str | None = None,
        timeout_sec: float | None = None,
        inference_target: str | None = None,
        provider: InferenceProvider | None = None,
    ) -> None:
        timeout = timeout_sec if timeout_sec is not None else OPENAI_TIMEOUT_SECONDS
        self.timeout_sec = max(1.0, float(timeout))

        if provider is not None:
            self.provider = provider
            self.provider_name = "custom"
            self.model = (
                str(model or OPENAI_MODEL or "gpt-4o-mini").strip() or "gpt-4o-mini"
            )
            self.api_base_url = _normalize_api_base_url(
                api_base_url or OPENAI_API_BASE_URL or "https://api.openai.com/v1"
            )
            return

        target = self._resolve_target(
            raw_target=inference_target or INFERENCE_TARGET,
            explicit_model=model,
        )
        self.provider_name = target.provider
        self.model = self._normalize_model_for_provider(target.provider, target.model)

        if target.provider == "openai":
            self.provider = OpenAIInferenceProvider(
                base_url=api_base_url,
                timeout_sec=self.timeout_sec,
            )
        elif target.provider == "gemini":
            self.provider = GeminiInferenceProvider(
                base_url=api_base_url,
                timeout_sec=self.timeout_sec,
            )
        elif target.provider == "openrouter":
            self.provider = OpenRouterInferenceProvider(
                base_url=api_base_url,
                timeout_sec=self.timeout_sec,
            )
        else:
            raise RuntimeError(
                f"Unsupported inference provider '{target.provider}'. "
                "Supported providers: openai, gemini, openrouter."
            )

        provider_base_url = getattr(self.provider, "base_url", None)
        self.api_base_url = _normalize_api_base_url(
            str(provider_base_url or api_base_url or OPENAI_API_BASE_URL)
        )

    async def infer(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        top_p: float,
        max_output_tokens: int = 500,
        logit_bias: dict[str, int] | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        tools: list[Any] | None = None,
    ) -> InferenceResult:
        logger.debug(
            "Inference start provider=%s model=%s messages=%s tools=%s",
            self.provider_name,
            self.model,
            len(messages),
            len(tools or []),
        )

        effective_top_p: float | None
        if self._supports_top_p(self.model):
            effective_top_p = float(top_p)
        else:
            effective_top_p = None

        effective_logit_bias = (
            logit_bias if self._supports_logit_bias(self.model) else None
        )

        request = InferenceRequest(
            model=self.model,
            messages=list(messages),
            temperature=float(temperature),
            top_p=effective_top_p,
            max_output_tokens=max_output_tokens,
            logit_bias=effective_logit_bias,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            tools=tools,
        )

        try:
            result = await self.provider.inference(request)
        except Exception as exc:
            logger.warning("Primary inference call failed: %s", exc)
            if effective_logit_bias:
                retry_request = InferenceRequest(
                    model=request.model,
                    messages=request.messages,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    max_output_tokens=request.max_output_tokens,
                    logit_bias=None,
                    frequency_penalty=request.frequency_penalty,
                    presence_penalty=request.presence_penalty,
                    tools=request.tools,
                )
                try:
                    result = await self.provider.inference(retry_request)
                except Exception as retry_exc:
                    raise RuntimeError(
                        f"LLM inference failed: {retry_exc}"
                    ) from retry_exc
            else:
                raise RuntimeError(f"LLM inference failed: {exc}") from exc

        logger.debug(
            "Inference success provider=%s model=%s tokens(in=%s out=%s total=%s) tools=%s",
            self.provider_name,
            result.model,
            result.input_tokens,
            result.output_tokens,
            result.total_tokens,
            len(result.tool_calls),
        )
        return result

    @staticmethod
    def _resolve_target(
        *,
        raw_target: str | None,
        explicit_model: str | None,
    ) -> InferenceTargetConfig:
        default_model = str(explicit_model or OPENAI_MODEL or "gpt-4o-mini").strip()
        if not default_model:
            default_model = "gpt-4o-mini"

        raw = str(raw_target or "").strip()
        if not raw:
            return InferenceTargetConfig(provider="openai", model=default_model)

        if ":" not in raw:
            # Backward-compatible legacy form where only model is provided.
            return InferenceTargetConfig(provider="openai", model=raw)

        provider_raw, model_raw = raw.split(":", 1)
        provider = provider_raw.strip().lower()
        provider_aliases = {
            "google": "gemini",
            "open-router": "openrouter",
            "router": "openrouter",
        }
        provider = provider_aliases.get(provider, provider)

        model = model_raw.strip()
        if not provider:
            provider = "openai"
        if not model:
            model = default_model

        if explicit_model:
            explicit = str(explicit_model).strip()
            if explicit:
                model = explicit

        return InferenceTargetConfig(provider=provider, model=model)

    @staticmethod
    def _normalize_model_for_provider(provider: str, model: str) -> str:
        cleaned = str(model or "").strip() or "gpt-4o-mini"
        if provider == "openai" and cleaned.startswith("openai/"):
            return cleaned.split("/", 1)[1].strip() or "gpt-4o-mini"
        return cleaned

    @staticmethod
    def _supports_top_p(model: str) -> bool:
        normalized = str(model or "").strip().lower()
        return not (
            normalized.startswith("gpt-5")
            or normalized.startswith("openai/gpt-5")
            or "/gpt-5" in normalized
        )

    @staticmethod
    def _supports_logit_bias(model: str) -> bool:
        normalized = str(model or "").strip().lower()
        return not (
            normalized.startswith("gpt-5")
            or normalized.startswith("openai/gpt-5")
            or "/gpt-5" in normalized
        )


def _normalize_api_base_url(raw: str) -> str:
    base = str(raw or "").strip().rstrip("/")
    if not base:
        return "https://api.openai.com/v1"

    lowered = base.lower()
    if "api.openai.com" in lowered and not lowered.endswith("/v1"):
        return f"{base}/v1"

    return base
