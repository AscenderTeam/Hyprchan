from dataclasses import dataclass
import os
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from settings import (
    OPENAI_API_BASE_URL,
    OPENAI_MODEL,
    OPENAI_OAUTH_TOKEN,
    OPENAI_TIMEOUT_SECONDS,
)


@dataclass
class InferenceResult:
    output: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    tool_calls: list[dict[str, Any]]
    raw: dict[str, Any]


class InferenceEngine:
    """LangChain-based inference bridge for HyprAI OS."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_base_url: str | None = None,
        timeout_sec: float | None = None,
    ) -> None:
        raw_model = model or OPENAI_MODEL or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        raw_api_base_url = (
            api_base_url
            or OPENAI_API_BASE_URL
            or os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
        )

        self.api_base_url = self._normalize_api_base_url(raw_api_base_url)
        self.model = self._normalize_model(raw_model, self.api_base_url)

        timeout = timeout_sec if timeout_sec is not None else OPENAI_TIMEOUT_SECONDS
        self.timeout_sec = max(1.0, float(timeout))

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
        lc_messages = self._to_langchain_messages(messages)
        effective_logit_bias = (
            logit_bias if self._supports_logit_bias(self.model) else None
        )

        try:
            response = await self._invoke_chat_model(
                messages=lc_messages,
                temperature=temperature,
                top_p=top_p,
                max_output_tokens=max_output_tokens,
                logit_bias=effective_logit_bias,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                tools=tools,
            )
        except Exception as exc:
            if effective_logit_bias:
                try:
                    response = await self._invoke_chat_model(
                        messages=lc_messages,
                        temperature=temperature,
                        top_p=top_p,
                        max_output_tokens=max_output_tokens,
                        logit_bias=None,
                        frequency_penalty=frequency_penalty,
                        presence_penalty=presence_penalty,
                        tools=tools,
                    )
                except Exception as retry_exc:
                    raise RuntimeError(
                        f"LLM inference failed: {retry_exc}"
                    ) from retry_exc
            else:
                raise RuntimeError(f"LLM inference failed: {exc}") from exc

        tool_calls = self._extract_tool_calls(response)
        output = self._extract_output(response, allow_empty=bool(tool_calls))
        input_tokens, output_tokens, total_tokens = self._extract_usage(response)

        return InferenceResult(
            output=output,
            model=self._extract_model(response),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            tool_calls=tool_calls,
            raw=self._extract_raw(response),
        )

    async def _invoke_chat_model(
        self,
        *,
        messages: list[BaseMessage],
        temperature: float,
        top_p: float,
        max_output_tokens: int,
        logit_bias: dict[str, int] | None,
        frequency_penalty: float | None,
        presence_penalty: float | None,
        tools: list[Any] | None,
    ) -> AIMessage:
        token = self._resolve_oauth_token()
        model_kwargs: dict[str, Any] = {}
        if logit_bias and self._supports_logit_bias(self.model):
            model_kwargs["logit_bias"] = logit_bias
        if frequency_penalty is not None:
            model_kwargs["frequency_penalty"] = float(frequency_penalty)
        if presence_penalty is not None:
            model_kwargs["presence_penalty"] = float(presence_penalty)
        model_kwargs["max_completion_tokens"] = max(64, int(max_output_tokens))

        chat_kwargs: dict[str, Any] = {
            "model": self.model,
            "api_key": SecretStr(token),
            "base_url": self.api_base_url,
            "timeout": self.timeout_sec,
            "temperature": float(temperature),
            "model_kwargs": model_kwargs,
        }
        if self._supports_top_p(self.model):
            chat_kwargs["top_p"] = float(top_p)

        llm = ChatOpenAI(
            **chat_kwargs,
        )

        if tools:
            llm = llm.bind_tools(tools)

        return await llm.ainvoke(messages)

    def _resolve_oauth_token(self) -> str:
        token = (
            OPENAI_OAUTH_TOKEN
            or os.getenv("OPENAI_OAUTH_TOKEN")
            or os.getenv("OPENAI_API_KEY")
        )
        if not token or token.startswith("your_"):
            raise RuntimeError(
                "Missing OpenAI OAuth token. Set OPENAI_OAUTH_TOKEN (preferred) or OPENAI_API_KEY in .env"
            )
        return token

    @staticmethod
    def _normalize_api_base_url(raw: str) -> str:
        base = str(raw or "").strip().rstrip("/")
        if not base:
            return "https://api.openai.com/v1"

        lowered = base.lower()
        if "api.openai.com" in lowered and not lowered.endswith("/v1"):
            return f"{base}/v1"

        return base

    @staticmethod
    def _normalize_model(raw_model: str, normalized_base_url: str) -> str:
        model = str(raw_model or "").strip()
        if not model:
            return "gpt-4o-mini"

        lowered_base = normalized_base_url.lower()
        if "api.openai.com" in lowered_base and model.startswith("openai/"):
            return model.split("/", 1)[1].strip() or "gpt-4o-mini"

        return model

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

    def _to_langchain_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[BaseMessage]:
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

    def _extract_output(self, response: Any, *, allow_empty: bool = False) -> str:
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

    def _extract_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        calls = getattr(response, "tool_calls", None)
        if isinstance(calls, list):
            normalized: list[dict[str, Any]] = []
            for call in calls:
                if not isinstance(call, dict):
                    continue
                name = str(call.get("name", "")).strip()
                args = call.get("args")
                if not name:
                    continue
                if not isinstance(args, dict):
                    args = {}
                normalized.append({"name": name, "args": args})
            return normalized

        return []

    def _extract_usage(self, response: Any) -> tuple[int, int, int]:
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

    def _extract_model(self, response: Any) -> str:
        response_meta = getattr(response, "response_metadata", None)
        if isinstance(response_meta, dict):
            model_name = response_meta.get("model_name") or response_meta.get("model")
            if isinstance(model_name, str) and model_name.strip():
                return model_name.strip()
        return self.model

    def _extract_raw(self, response: Any) -> dict[str, Any]:
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
