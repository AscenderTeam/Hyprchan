from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Sequence

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, BaseMessage, ToolMessage
from langchain_core.agents import AgentAction

from hyprchan import settings
from pydantic import SecretStr


class ReActAgentExecutor:
    """
    Refactored Agent Executor using LangChain's tool calling agent.
    It supports multimodal tool outputs and preserves the 'Reasoning and Acting' (ReAct) loop
    using native tool calling and messages.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: Sequence[StructuredTool],
        *,
        system_prompt: str,
    ) -> None:
        self._llm = llm
        
        # We use a ChatPromptTemplate with placeholders for history, input, and scratchpad.
        # The ReAct instructions are assumed to be part of the system_prompt.
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt.replace("{", "{{").replace("}", "}}")),
                MessagesPlaceholder("chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder("agent_scratchpad"),
            ]
        )
        
        # custom message formatter to handle multimodal tool outputs
        def custom_message_formatter(intermediate_steps: Sequence[tuple[AgentAction, Any]]) -> list[BaseMessage]:
            messages: list[BaseMessage] = []
            for action, observation in intermediate_steps:
                # Add the assistant's message that called the tool
                messages.extend(action.message_log)

                # If observation is a tuple (text, images_metadata), we convert metadata to blocks
                if isinstance(observation, tuple) and len(observation) == 2 and isinstance(observation[1], list):
                    text, images_metadata = observation
                    messages.append(ToolMessage(content=str(text), tool_call_id=action.tool_call_id))
                    
                    # Convert metadata to image blocks for a subsequent HumanMessage
                    image_blocks = []
                    for img in images_metadata:
                        if not isinstance(img, dict) or "path" not in img:
                            continue
                        
                        path = Path(img["path"])
                        if not path.exists():
                            continue
                            
                        mime = img.get("mime")
                        if not mime:
                            guessed, _ = mimetypes.guess_type(path.name)
                            mime = guessed or "image/jpeg"
                            
                        try:
                            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                            data_url = f"data:{mime};base64,{encoded}"
                            image_blocks.append({
                                "type": "image_url", 
                                "image_url": {"url": data_url, "detail": "low"}
                            })
                        except Exception:
                            continue
                            
                    if image_blocks:
                        messages.append(HumanMessage(content=image_blocks))
                else:
                    messages.append(ToolMessage(content=str(observation), tool_call_id=action.tool_call_id))
            return messages

        # create_tool_calling_agent handles the loop
        agent = create_tool_calling_agent(
            self._llm, 
            tools=list(tools), 
            prompt=prompt,
            message_formatter=custom_message_formatter
        )
        
        self._executor = AgentExecutor(
            agent=agent, 
            tools=list(tools), 
            verbose=True, 
            handle_parsing_errors=True,
            max_iterations=10,
        )

    async def ainvoke(
        self, 
        *, 
        user_input: str, 
        chat_history: list[BaseMessage] | None = None,
        **kwargs: Any
    ) -> dict[str, Any]:
        """Run the agent; returns {output, intermediate_steps}."""
        inputs = {
            "input": user_input,
            "chat_history": chat_history or [],
        }
            
        result = await self._executor.ainvoke(inputs)
        return {
            "output": result.get("output", ""),
            "intermediate_steps": result.get("intermediate_steps", []),
        }
