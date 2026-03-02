import asyncio
from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, request

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
    raw: dict[str, Any]


class InferenceEngine:
    """
    OpenAI GPT-5.3 inference bridge using OAuth bearer authorization.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_base_url: str | None = None,
        timeout_sec: float | None = None,
    ) -> None:
        self.model = (
            model or OPENAI_MODEL or os.getenv("OPENAI_MODEL", "openai/gpt-5.3")
        )
        self.api_base_url = (
            api_base_url
            or OPENAI_API_BASE_URL
            or os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com")
        ).rstrip("/")
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
    ) -> InferenceResult:
        if logit_bias:
            chat_payload = {
                "model": self.model,
                "messages": messages,
                "temperature": float(temperature),
                "top_p": float(top_p),
                "max_completion_tokens": max(64, int(max_output_tokens)),
                "logit_bias": logit_bias,
            }
            if frequency_penalty is not None:
                chat_payload["frequency_penalty"] = float(frequency_penalty)
            if presence_penalty is not None:
                chat_payload["presence_penalty"] = float(presence_penalty)

            data = await self._post_json("/v1/chat/completions", chat_payload)
            output = self._extract_output(data)
            usage = data.get("usage", {})

            input_tokens = int(
                usage.get("input_tokens", usage.get("prompt_tokens", 0) or 0)
            )
            output_tokens = int(
                usage.get("output_tokens", usage.get("completion_tokens", 0) or 0)
            )
            total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens))

            return InferenceResult(
                output=output,
                model=str(data.get("model", self.model)),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                raw=data,
            )

        payload = {
            "model": self.model,
            "input": messages,
            "temperature": float(temperature),
            "top_p": float(top_p),
            "max_output_tokens": max(64, int(max_output_tokens)),
        }

        try:
            data = await self._post_json("/v1/responses", payload)
        except RuntimeError:
            fallback_payload = {
                "model": self.model,
                "messages": messages,
                "temperature": float(temperature),
                "top_p": float(top_p),
                "max_completion_tokens": max(64, int(max_output_tokens)),
            }
            if frequency_penalty is not None:
                fallback_payload["frequency_penalty"] = float(frequency_penalty)
            if presence_penalty is not None:
                fallback_payload["presence_penalty"] = float(presence_penalty)

            data = await self._post_json("/v1/chat/completions", fallback_payload)

        output = self._extract_output(data)
        usage = data.get("usage", {})

        input_tokens = int(
            usage.get("input_tokens", usage.get("prompt_tokens", 0) or 0)
        )
        output_tokens = int(
            usage.get("output_tokens", usage.get("completion_tokens", 0) or 0)
        )
        total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens))

        return InferenceResult(
            output=output,
            model=str(data.get("model", self.model)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            raw=data,
        )

    async def _post_json(
        self, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        token = self._resolve_oauth_token()
        url = f"{self.api_base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        def _do_request() -> dict[str, Any]:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(url=url, data=body, headers=headers, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw_data = resp.read().decode("utf-8")
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(
                    f"OpenAI API returned HTTP {exc.code}: {detail}"
                ) from exc
            except error.URLError as exc:
                raise RuntimeError(
                    f"OpenAI API connection error: {exc.reason}"
                ) from exc

            try:
                return json.loads(raw_data)
            except json.JSONDecodeError as exc:
                raise RuntimeError("OpenAI API response is not valid JSON") from exc

        return await asyncio.to_thread(_do_request)

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

    def _extract_output(self, data: dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output_nodes = data.get("output", [])
        if isinstance(output_nodes, list):
            chunks: list[str] = []
            for node in output_nodes:
                if not isinstance(node, dict):
                    continue
                contents = node.get("content", [])
                if not isinstance(contents, list):
                    continue
                for content in contents:
                    if not isinstance(content, dict):
                        continue
                    text_val = content.get("text")
                    if isinstance(text_val, str):
                        chunks.append(text_val)
            if chunks:
                return "\n".join(chunks).strip()

        choices = data.get("choices", [])
        if isinstance(choices, list) and choices:
            first_choice = choices[0] or {}
            message = first_choice.get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()

        raise RuntimeError("OpenAI API response did not include textual output")
