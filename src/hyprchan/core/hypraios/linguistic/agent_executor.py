from __future__ import annotations

from typing import Any, Sequence

from langchain.agents import AgentExecutor, create_react_agent
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import StructuredTool

import settings
from pydantic import SecretStr


def default_react_prompt() -> PromptTemplate:
    # Lightweight ReAct prompt to avoid hub dependency.
    template = """You are Hyprchan, a helpful but concise desktop agent.
Use the tools when they are useful. Think step-by-step. If no tool is needed, just answer.
Format:
Thought: what you think
Action: tool name
Action Input: JSON arguments
Observation: tool result
... (repeat as needed)
Final Answer: your final reply to the user"""
    return PromptTemplate.from_template(template)


class ReActAgentExecutor:
    """Minimal ReAct agent wired to the existing tool runtime tools."""

    def __init__(
        self,
        llm: BaseChatModel | None,
        tools: Sequence[StructuredTool],
        prompt: PromptTemplate | None = None,
    ) -> None:
        self._llm = llm or self._build_default_llm()
        self._prompt = prompt or default_react_prompt()
        agent = create_react_agent(self._llm, tools=list(tools), prompt=self._prompt)
        self._executor = AgentExecutor(agent=agent, tools=list(tools), verbose=False)

    async def ainvoke(self, *, user_input: str, **kwargs: Any) -> dict[str, Any]:
        """Run the ReAct agent; returns {output, intermediate_steps}."""
        result = await self._executor.ainvoke({"input": user_input, **kwargs})
        return {
            "output": result.get("output", ""),
            "intermediate_steps": result.get("intermediate_steps", []),
        }

    @staticmethod
    def _build_default_llm() -> BaseChatModel:
        return ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=SecretStr(settings.OPENAI_OAUTH_TOKEN or settings.OPENAI_API_KEY),
            base_url=settings.OPENAI_API_BASE_URL,
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
            temperature=0.2,
        )
