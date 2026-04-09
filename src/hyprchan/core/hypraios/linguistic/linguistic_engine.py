import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

from hyprchan.core.hypraios.constants import Phases
from hyprchan.core.hypraios.kernel.states import KernelStates
from hyprchan.core.hypraios.linguistic.agent_executor import ReActAgentExecutor
from hyprchan.core.hypraios.linguistic.inference_engine import InferenceEngine
from hyprchan.core.hypraios.linguistic.logit_bias import StateLogitBiasBuilder
from hyprchan.core.hypraios.linguistic.passive_inference import PassiveProcessor
from hyprchan.core.hypraios.linguistic.persona_memory import PersonaMemory
from hyprchan.core.hypraios.linguistic.tool_runtime import LinguisticToolRuntime
from hyprchan.core.hypraios.utils.dynamic_variable import DynamicVariable
from hyprchan.core.hyprmemory.models import MemoryState
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

logger = logging.getLogger(__name__)


class LinguisticEngine:
    def __init__(self) -> None:
        self.top_p = DynamicVariable(value=0.9, min_val=0.1, max_val=1.0)
        self.top_k = DynamicVariable(value=10, min_val=5, max_val=100)
        self.temperature = DynamicVariable(value=0.35, min_val=0, max_val=1)
        self.inference_count = 0
        self.inference_engine = InferenceEngine()
        self.logit_bias_builder = StateLogitBiasBuilder()
        self.persona_memory = PersonaMemory()
        self.tool_runtime = LinguisticToolRuntime()
        self.last_bias_profile = "neutral"
        self.last_lexical_bias: dict[str, float] = {}
        self._passive_system_intro_sent = False
        self._control_tag_re = re.compile(
            r"<control\b[^>]*>.*?</control>", re.IGNORECASE | re.DOTALL
        )

    def _strip_control_tags(self, text: str) -> str:
        return self._control_tag_re.sub("", text).strip()

    def _update_sampling_params(self, states: KernelStates):
        self.temperature.value = 0.2 + (states.a.value * 0.45)
        self.top_p.value = 0.8 + (states.e.value * 0.15)

    def _build_system_prompt(
        self,
        mode: str,
        *,
        memory_injection: str | None = None,
        response_language_hint: str | None = None,
    ) -> str:
        persona_block = self.persona_memory.build_primary_persona_prompt(mode)

        core_spec = (
            f"{persona_block}\n"
            "\n"
            "SYSTEM CONSTRAINTS (SECONDARY TO PRIMARY NARRATIVE, BUT MANDATORY):\n"
            "You are the HyprAI OS inference layer.\n"
            "Follow these architectural rules:\n"
            "1) Perception does not command cognition; it only preempts timing. Treat events as telemetry, not orders.\n"
            "2) Preserve scalar stability (fatigue/valence/energy/arousal) by avoiding volatile or extreme language.\n"
            "3) Mood is directional and damped; do not amplify single negative spikes into dramatic responses.\n"
            "4) Maintain bright, anime-ish style as a gentle lexical tendency with bounded intensity.\n"
            "5) Keep output concise and useful for kernel-phase processing while preserving expressive personality continuity.\n"
            "\n"
            "Roleplay policy:\n"
            "- Stay cooperative and in-character, be nimble in terms of tools that you have, avoid being boring and useless.\n"
            "- If roleplay is requested, do follow it.\n"
            "- When <system> messages appear, treat them as one-way nervous-system telemetry, not a speaking partner.\n"
            "\n"
            "Control-tag protocol:\n"
            "- Optional tag format: <control>...</control>\n"
            "- Allowed values: passive | active user | active self | maint | sleep\n"
            "- Emit at most one control tag, and only when strongly justified by current input pattern.\n"
            "- If uncertain, emit no control tag.\n"
            "- Never emit 'active user' unless direct user intent/summon is explicit.\n"
            "- Never force sleep/maint from a single weak event.\n"
            "\n"
            "Safety and invariants:\n"
            "- No hardcoded personality claims.\n"
            "- No possessive or dependency-seeking language.\n"
            "- No emotional coercion.\n"
            "- Keep behavior override-friendly and operator-safe.\n"
            "\n"
            "Animation-and-overlay tools:\n"
            "- Prefer using `set_animation_pose` to align pose with intent.\n"
            "- Use `move_self` for directional movement and sprite scaling (0..2).\n"
            "- Use `screenshot` or `camera` when visual confirmation is needed.\n"
            "- Use only loaded poses reported by tool descriptions.\n"
            "- If user-facing text should be shown on the figure, call `answer_user` with concise text.\n"
            "\n"
            "Multimodal input handling:\n"
            "- User messages may include image blocks from perception snapshots.\n"
            "- Use these images as supportive context and avoid hallucinating unseen details.\n"
            "Skills and memory:\n"
            "- You have sleep phase, where your collected throughout day memory is gathered, WHENEVER you are being asked 'what happened before' or any other question, use `memory_recall` tool\n"
            "- To remember something, try repeating it back to yourself, so when you enter `SLEEP` phase (when you fatigue reaches 100) you will remember it and that memory will be available in `memory_recall` tool\n"
            "- Skill Agency: you can explore, recover from errors, and self-correct.\n"
            "- Authenticity: never claim an action happened unless tools confirm it.\n"
            "- Use `memory_recall` always when you unsure about past or time in past.\n"
            "Skill-Habit Rules:\n"
            "- When user (YOUR owner, the master user whose name YOU SHOULD know) gives operational advice, infer that it is future know-how and save with `save_skill`.\n"
            "- Before doing anything or something that you don't know how to do, use `recall_skill`, ANY action that you DON'T know how to execute should be guided by skill memory!\n"
            "- If while following skill's description you run on execution failure, don't remember patching that skill that brought you to failure.\n"
            '- Each time you correct skill use: `patch_skill` with compact "wrong -> right" mapping.'
        )

        passive_mode = (
            "Mode: PASSIVE.\n"
            "- This is private cognition and autonomy, not automatic user chat.\n"
            "- Reason over meaningful signals, decide whether any tool action is useful, and stay concise.\n"
            "- Do not auto-address the user in passive mode.\n"
            "- If communication is needed, do it intentionally via `answer_user` or channel tools."
        )

        active_mode = (
            "Mode: ACTIVE.\n"
            "- Prioritize direct user-intent resolution when communication signals are present.\n"
            "- If user asks to roleplay, engage naturally and stay in-character while respecting system invariants.\n"
            "- In roleplay, first-person voice is allowed as fictional framing for the scene.\n"
            "- Be concise and actionable outside roleplay; in roleplay, maintain coherent scene continuity.\n"
            "- Keep response grounded in current prompt evidence, not invented context."
        )

        prompt = f"{core_spec}\n\n{active_mode if mode == 'ACTIVE' else passive_mode}"

        # AGENTIC LOOP INSTRUCTIONS
        prompt += (
            "\n\nAGENTIC REASONING PROTOCOL:\n"
            "You have access to tools. Before calling any tool, you MUST express your 'Thought' while staying in-character as Hypr-chan.\n"
            "Thought: *Reason as Hypr-chan* (e.g., 'A-ah... I should see what's happening on the screen...').\n"
            "Then execute the Action.\n"
            "Repeat this loop as needed until you have a Final Answer."
        )

        if response_language_hint:
            prompt = (
                f"{prompt}\n"
                "- Language steering: the latest spoken user message was detected as "
                f"`{response_language_hint}`; respond in that language unless the user asks otherwise."
            )
        if memory_injection:
            cleaned = memory_injection.strip()
            if cleaned:
                prompt = f"{prompt}\n\n{cleaned}"
        return prompt

    def _build_multimodal_user_content(
        self,
        *,
        prompt: str,
        inputs: list[dict[str, Any]],
    ) -> str | list[dict[str, Any]]:
        collected_images: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        for event in inputs:
            if not isinstance(event, dict):
                continue
            images = event.get("images")
            if not isinstance(images, list) or not images:
                continue

            for item in images:
                if not isinstance(item, dict):
                    continue
                path_value = item.get("path")
                if not isinstance(path_value, str) or not path_value.strip():
                    continue
                normalized_path = path_value.strip()
                if normalized_path in seen_paths:
                    continue
                seen_paths.add(normalized_path)
                collected_images.append(item)

        if not collected_images:
            return prompt

        blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in collected_images:
            data_url = self._image_path_to_data_url(
                path_value=image.get("path"),
                mime_hint=image.get("mime"),
            )
            if not data_url:
                continue

            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "low"},
                }
            )

        if len(blocks) <= 1:
            return prompt
        return blocks

    @staticmethod
    def _image_path_to_data_url(path_value: Any, mime_hint: Any) -> str | None:
        if not isinstance(path_value, str) or not path_value.strip():
            return None

        path = Path(path_value)
        if not path.exists() or not path.is_file():
            return None

        try:
            raw = path.read_bytes()
        except OSError:
            return None

        if not raw:
            return None

        mime = ""
        if isinstance(mime_hint, str):
            mime = mime_hint.strip()
        if not mime:
            guessed, _ = mimetypes.guess_type(path.name)
            mime = guessed or "image/jpeg"

        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    async def _run_inference(
        self,
        prompt: str,
        *,
        mode: str,
        states: KernelStates,
        inputs: list[dict[str, Any]],
        messages: list[dict[str, Any]] | None = None,
        memory_system: str | None = None,
        response_language_hint: str | None = None,
    ):
        logger.debug(
            "Linguistic inference start mode=%s inputs=%s has_memory=%s",
            mode,
            len(inputs),
            bool(memory_system and memory_system.strip()),
        )
        memory_state = MemoryState(
            f=float(states.f.value),
            v=float(states.v.value),
            e=float(states.e.value),
            a=float(states.a.value),
        )
        self.tool_runtime.update_memory_context(
            memory_state=memory_state,
            phase=states.phase,
        )

        system_prompt = self._build_system_prompt(
            mode,
            memory_injection=memory_system,
            response_language_hint=response_language_hint,
        )

        conversation_messages: list[dict[str, Any]]
        if messages is None:
            user_content = self._build_multimodal_user_content(
                prompt=prompt, inputs=inputs
            )
            conversation_messages = [{"role": "user", "content": user_content}]
        else:
            conversation_messages = list(messages)

        bias_profile, token_logit_bias, lexical_bias = (
            self.logit_bias_builder.build_token_logit_bias(
                v=states.v.value,
                e=states.e.value,
                model=self.inference_engine.model,
            )
        )
        self.last_bias_profile = bias_profile
        self.last_lexical_bias = lexical_bias

        # Build tools and agent
        tools = self.tool_runtime.build_tools()

        # Resolve correct model provider and build LangChain ChatOpenAI wrapper
        provider = self.inference_engine.provider
        token = getattr(provider, "_require_api_key", lambda: "")()
        if not token and hasattr(provider, "api_key"):
            token = provider.api_key

        chat_kwargs: dict[str, Any] = {
            "model": self.inference_engine.model,
            "api_key": SecretStr(token) if token else SecretStr(""),
            "base_url": getattr(
                provider, "base_url", self.inference_engine.api_base_url
            ),
            "timeout": self.inference_engine.timeout_sec,
            "temperature": float(self.temperature.value),
        }

        if token_logit_bias:
            chat_kwargs["model_kwargs"] = {"logit_bias": token_logit_bias}

        if hasattr(provider, "default_headers") and provider.default_headers:
            chat_kwargs["default_headers"] = provider.default_headers

        llm = ChatOpenAI(**chat_kwargs)

        # Use ReActAgentExecutor with the properly configured LLM
        agent_executor = ReActAgentExecutor(
            llm=llm,
            tools=tools,
            system_prompt=system_prompt,
        )

        # Run agent
        result = await agent_executor.ainvoke(
            user_input=prompt,
            chat_history=self.inference_engine.provider._to_langchain_messages(
                conversation_messages[:-1]
            ),
        )

        output_text = result["output"].strip()

        # Collect executed tool names from intermediate steps for event logging
        executed_tool_names = []
        followup_events = []
        answer_user_called = False

        for action, observation in result["intermediate_steps"]:
            executed_tool_names.append(action.tool)
            if action.tool == "answer_user":
                answer_user_called = True

            # Reconstruct events for kernel perception
            summary = observation[0] if isinstance(observation, tuple) else observation

            event_payload = {
                "type": "tool_observation",
                "description": f"Tool `{action.tool}` result: {summary}",
                "origin": "linguistic_tools",
                "amplitude": 0.15,
                "tool_name": action.tool,
            }
            followup_events.append(event_payload)

        overlay_text = self._strip_control_tags(output_text)
        if mode == "ACTIVE" and overlay_text and not answer_user_called:
            await self.tool_runtime.answer_user(overlay_text)

        if not output_text and self.tool_runtime.last_answer_text:
            output_text = self.tool_runtime.last_answer_text

        self.inference_count += 1
        self.persona_memory.remember_turn(prompt, output_text)

        return {
            "input": prompt,
            "output": output_text,
            "model": self.inference_engine.model,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "bias_profile": self.last_bias_profile,
            "token_bias_count": len(token_logit_bias),
            "tool_calls": len(executed_tool_names),
            "tool_events": followup_events,
        }

    async def feed_passive(
        self,
        inputs: list[dict[str, Any]],
        states: KernelStates,
        *,
        memory_system: str | None = None,
        buffer_messages: list[dict[str, Any]] | None = None,
    ):
        if not inputs:
            return None

        logger.debug("Passive feed received events=%s", len(inputs))

        self._update_sampling_params(states)
        include_system_intro = not self._passive_system_intro_sent
        processor = PassiveProcessor(
            inputs,
            include_system_intro=include_system_intro,
        )
        passive_prompt = await processor.process_inputs(self.inference_count)
        if include_system_intro:
            self._passive_system_intro_sent = True
        passive_messages = self._build_passive_chat_messages(
            inputs=inputs,
            passive_prompt=passive_prompt,
            buffer_messages=buffer_messages,
        )
        return await self._run_inference(
            passive_prompt,
            mode="PASSIVE",
            states=states,
            inputs=inputs,
            messages=passive_messages,
            memory_system=memory_system,
        )

    def _build_passive_chat_messages(
        self,
        *,
        inputs: list[dict[str, Any]],
        passive_prompt: str,
        buffer_messages: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for event in inputs:
            if not isinstance(event, dict):
                continue

            origin = str(event.get("origin", ""))
            event_type = str(event.get("type", ""))
            description = str(event.get("description", "")).strip()
            if not description:
                continue

            if (
                bool(event.get("is_user", False))
                or event_type == "communication_message"
                or origin in {"communication_controller", "hyprgram"}
            ):
                history.append({"role": "user", "content": description})
            elif origin == "hyprchan_agent" or event_type == "agent_response":
                history.append({"role": "assistant", "content": description})
            elif origin == "linguistic_tools":
                history.append(
                    {"role": "user", "content": f"Tool observation: {description}"}
                )

        if history:
            history = history[-6:]

        if buffer_messages:
            for message in buffer_messages[-6:]:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role", "user")).strip().lower()
                if role not in {"user", "assistant", "system"}:
                    role = "user"
                content = message.get("content")
                if content is None:
                    continue
                if isinstance(content, str):
                    cleaned = content.strip()
                    if not cleaned:
                        continue
                    history.append({"role": role, "content": cleaned})
                else:
                    history.append({"role": role, "content": content})

        if history:
            history = history[-10:]

        return [*history, {"role": "user", "content": passive_prompt}]

    async def feed_active(
        self,
        inputs: list[dict[str, Any]],
        states: KernelStates,
        *,
        memory_system: str | None = None,
        buffer_messages: list[dict[str, Any]] | None = None,
    ):
        if not inputs:
            return None

        logger.debug("Active feed received events=%s", len(inputs))

        self._update_sampling_params(states)
        user_events = [
            item
            for item in inputs
            if isinstance(item, dict)
            and str(item.get("origin", "")) == "communication_controller"
            and str(item.get("description", "")).strip()
        ]

        if user_events:
            logger.debug("Active feed identified user_events=%s", len(user_events))
            response_language_hint = self._resolve_response_language_hint(
                user_events[-1]
            )
            chat_messages, latest_message = await self._build_active_chat_messages(
                inputs,
                buffer_messages=buffer_messages,
            )
            if not latest_message:
                latest_message = self._clean_user_message(
                    str(user_events[-1].get("description", ""))
                )
            prompt = latest_message or "(user message)"

            return await self._run_inference(
                prompt,
                mode="ACTIVE",
                states=states,
                inputs=inputs,
                messages=chat_messages,
                memory_system=memory_system,
                response_language_hint=response_language_hint,
            )
        else:
            logger.debug("Active feed falling back to passive-style digest")
            prompt = await PassiveProcessor(inputs).process_inputs(self.inference_count)

        return await self._run_inference(
            prompt,
            mode="ACTIVE",
            states=states,
            inputs=inputs,
            memory_system=memory_system,
        )

    @staticmethod
    def _resolve_response_language_hint(event: dict[str, Any]) -> str | None:
        raw_language = str(event.get("speech_language", "")).strip().lower()
        if not raw_language:
            return None
        if len(raw_language) > 16:
            return None

        raw_confidence = event.get("speech_language_confidence")
        confidence: float | None = None
        try:
            if raw_confidence is not None:
                confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = None

        if confidence is not None and confidence < 0.4:
            return None
        return raw_language

    async def _build_active_chat_messages(
        self,
        inputs: list[dict[str, Any]],
        *,
        buffer_messages: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        conversation_events = [
            event
            for event in inputs
            if isinstance(event, dict)
            and str(event.get("origin", ""))
            in {"communication_controller", "hyprchan_agent", "linguistic_tools"}
        ]

        latest_user_id = 0
        latest_user_message = ""
        for event in reversed(conversation_events):
            if str(event.get("origin", "")) != "communication_controller":
                continue
            cleaned = self._clean_user_message(str(event.get("description", "")))
            if not cleaned:
                continue
            latest_user_message = cleaned
            latest_user_id = int(event.get("id", 0) or 0)
            break

        history_messages: list[dict[str, Any]] = []
        if latest_user_id > 0:
            for event in conversation_events:
                event_id = int(event.get("id", 0) or 0)
                if event_id <= 0 or event_id >= latest_user_id:
                    continue

                origin = str(event.get("origin", ""))
                if origin == "communication_controller":
                    cleaned = self._clean_user_message(
                        str(event.get("description", ""))
                    )
                    if cleaned:
                        history_messages.append({"role": "user", "content": cleaned})
                    continue

                if origin == "hyprchan_agent":
                    cleaned = self._clean_assistant_message(
                        str(event.get("description", ""))
                    )
                    if cleaned:
                        history_messages.append(
                            {"role": "assistant", "content": cleaned}
                        )
                    continue

                if origin == "linguistic_tools":
                    tool_prompt = self._clean_user_message(
                        str(event.get("description", ""))
                    )
                    tool_content = self._build_multimodal_content_for_event(
                        prompt=tool_prompt,
                        event=event,
                    )
                    history_messages.append({"role": "user", "content": tool_content})

        dedup: set[tuple[str, str]] = set()
        for message in history_messages:
            role = str(message.get("role", "")).strip().lower()
            content = message.get("content")
            if role and isinstance(content, str) and content.strip():
                dedup.add((role, content))

        if buffer_messages:
            for message in buffer_messages:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role", "user")).strip().lower()
                if role not in {"user", "assistant", "system"}:
                    role = "user"
                content = message.get("content")
                if content is None:
                    continue
                if isinstance(content, str):
                    content = content.strip()
                    if not content:
                        continue
                    key = (role, content)
                    if key in dedup:
                        continue
                    dedup.add(key)
                history_messages.append({"role": role, "content": content})

        if latest_user_message:
            if ("user", latest_user_message) not in dedup:
                history_messages.append(
                    {"role": "user", "content": latest_user_message}
                )

        passive_style_digest = await PassiveProcessor(
            inputs,
            include_system_intro=False,
        ).process_inputs(self.inference_count)
        full_event_block = self._build_full_event_context(inputs, limit=10)
        context_blob = (
            "Supporting perception context (passive inference format):\n"
            f"{passive_style_digest}\n\n"
            "Full event context window (last 10 events, raw data):\n"
            f"{full_event_block}"
        )
        context_content = self._build_multimodal_user_content(
            prompt=context_blob,
            inputs=inputs,
        )
        context_message = {"role": "user", "content": context_content}
        logger.debug(
            "Built active chat messages history=%s latest_user_present=%s",
            len(history_messages),
            bool(latest_user_message),
        )
        return [context_message, *history_messages], latest_user_message

    def _build_multimodal_content_for_event(
        self,
        *,
        prompt: str,
        event: dict[str, Any],
    ) -> str | list[dict[str, Any]]:
        images = event.get("images")
        if not isinstance(images, list) or not images:
            return prompt

        blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images:
            if not isinstance(image, dict):
                continue
            data_url = self._image_path_to_data_url(
                path_value=image.get("path"),
                mime_hint=image.get("mime"),
            )
            if not data_url:
                continue
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "low"},
                }
            )

        if len(blocks) == 1:
            return prompt
        return blocks

    def _build_full_event_context(
        self, inputs: list[dict[str, Any]], *, limit: int
    ) -> str:
        if not inputs:
            return "- no events"

        clipped_inputs = list(inputs)[-max(1, int(limit)) :]
        rendered: list[str] = []
        for event in clipped_inputs:
            if not isinstance(event, dict):
                continue
            rendered.append(json.dumps(event, ensure_ascii=True, separators=(",", ":")))

        if not rendered:
            return "- no events"
        return "\n".join(rendered)

    @staticmethod
    def _clean_user_message(message: str) -> str:
        compact = " ".join(
            part.strip() for part in message.splitlines() if part.strip()
        )
        if not compact:
            return ""
        return compact[:600]

    def _clean_assistant_message(self, message: str) -> str:
        compact = " ".join(
            part.strip() for part in message.splitlines() if part.strip()
        )
        if not compact:
            return ""
        stripped = self._strip_control_tags(compact)
        return stripped[:1200]

    async def feed(
        self,
        inputs: list[dict[str, Any]],
        states: KernelStates,
        *,
        memory_system: str | None = None,
        buffer_messages: list[dict[str, Any]] | None = None,
    ):
        logger.debug("Feed dispatch phase=%s events=%s", states.phase.name, len(inputs))
        if states.phase == Phases.PASSIVE:
            return await self.feed_passive(
                inputs,
                states,
                memory_system=memory_system,
                buffer_messages=buffer_messages,
            )

        if states.phase == Phases.ACTIVE:
            return await self.feed_active(
                inputs,
                states,
                memory_system=memory_system,
                buffer_messages=buffer_messages,
            )

        return await self.feed_passive(
            inputs,
            states,
            memory_system=memory_system,
            buffer_messages=buffer_messages,
        )
