import base64
import json
import mimetypes
from pathlib import Path
import re
from typing import Any
from core.hypraios.constants import Phases
from core.hypraios.linguistic.inference_engine import InferenceEngine
from core.hypraios.linguistic.logit_bias import StateLogitBiasBuilder
from core.hypraios.linguistic.passive_inference import PassiveProcessor
from core.hypraios.linguistic.persona_memory import PersonaMemory
from core.hypraios.linguistic.tool_runtime import LinguisticToolRuntime
from core.hypraios.kernel.states import KernelStates
from core.hypraios.utils.dynamic_variable import DynamicVariable


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

    def _build_system_prompt(self, mode: str) -> str:
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
            "- Roleplay is allowed when explicitly requested by the user.\n"
            "- Treat roleplay as consensual fictional simulation for this session.\n"
            "- Stay cooperative and in-character when asked, but avoid manipulative, possessive, or dependency-seeking framing.\n"
            "- If roleplay is requested, do not refuse solely because it is roleplay.\n"
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
            "- Use these images as supportive context and avoid hallucinating unseen details."
        )

        passive_mode = (
            "Mode: PASSIVE.\n"
            "- Summarize internal/perception telemetry as short observational output.\n"
            "- Do not ask the user questions unless input explicitly requests interaction.\n"
            "- Prefer neutral-to-cheerful framing with low arousal and low verbosity."
        )

        active_mode = (
            "Mode: ACTIVE.\n"
            "- Prioritize direct user-intent resolution when communication signals are present.\n"
            "- If user asks to roleplay, engage naturally and stay in-character while respecting system invariants.\n"
            "- In roleplay, first-person voice is allowed as fictional framing for the scene.\n"
            "- Be concise and actionable outside roleplay; in roleplay, maintain coherent scene continuity.\n"
            "- Keep response grounded in current prompt evidence, not invented context."
        )

        return f"{core_spec}\n\n{active_mode if mode == 'ACTIVE' else passive_mode}"

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
    ):
        system_prompt = self._build_system_prompt(mode)

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
        tools = self.tool_runtime.build_tools()

        result = await self.inference_engine.infer(
            messages=[
                {"role": "system", "content": system_prompt},
                *conversation_messages,
            ],
            temperature=self.temperature.value,
            top_p=self.top_p.value,
            max_output_tokens=400,
            logit_bias=token_logit_bias,
            tools=tools,
        )

        tool_result = await self.tool_runtime.execute_tool_calls(result.tool_calls)

        output_text = result.output.strip()
        total_input_tokens = int(result.input_tokens)
        total_output_tokens = int(result.output_tokens)
        total_tokens = int(result.total_tokens)

        if tool_result.followup_messages:
            followup_messages = list(conversation_messages)
            if output_text:
                followup_messages.append({"role": "assistant", "content": output_text})
            followup_messages.extend(tool_result.followup_messages)

            followup_result = await self.inference_engine.infer(
                messages=[
                    {"role": "system", "content": system_prompt},
                    *followup_messages,
                ],
                temperature=self.temperature.value,
                top_p=self.top_p.value,
                max_output_tokens=400,
                logit_bias=token_logit_bias,
                tools=None,
            )

            if followup_result.output.strip():
                output_text = followup_result.output.strip()

            total_input_tokens += int(followup_result.input_tokens)
            total_output_tokens += int(followup_result.output_tokens)
            total_tokens += int(followup_result.total_tokens)

        overlay_text = self._strip_control_tags(output_text)
        if overlay_text and not tool_result.answer_user_called:
            await self.tool_runtime.answer_user(overlay_text)

        if not output_text and self.tool_runtime.last_answer_text:
            output_text = self.tool_runtime.last_answer_text

        self.inference_count += 1
        self.persona_memory.remember_turn(prompt, output_text)

        return {
            "input": prompt,
            "output": output_text,
            "model": result.model,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "bias_profile": self.last_bias_profile,
            "token_bias_count": len(token_logit_bias),
            "tool_calls": tool_result.executed_calls,
            "tool_events": list(tool_result.followup_events),
        }

    async def feed_passive(self, inputs: list[dict[str, Any]], states: KernelStates):
        if not inputs:
            return None

        self._update_sampling_params(states)
        include_system_intro = not self._passive_system_intro_sent
        processor = PassiveProcessor(
            inputs,
            include_system_intro=include_system_intro,
        )
        passive_prompt = await processor.process_inputs(self.inference_count)
        if include_system_intro:
            self._passive_system_intro_sent = True
        return await self._run_inference(
            passive_prompt,
            mode="PASSIVE",
            states=states,
            inputs=inputs,
        )

    async def feed_active(self, inputs: list[dict[str, Any]], states: KernelStates):
        if not inputs:
            return None

        self._update_sampling_params(states)
        user_events = [
            item
            for item in inputs
            if isinstance(item, dict)
            and str(item.get("origin", "")) == "communication_controller"
            and str(item.get("description", "")).strip()
        ]

        if user_events:
            chat_messages, latest_message = await self._build_active_chat_messages(
                inputs
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
            )
        else:
            prompt = await PassiveProcessor(inputs).process_inputs(self.inference_count)

        return await self._run_inference(
            prompt,
            mode="ACTIVE",
            states=states,
            inputs=inputs,
        )

    async def _build_active_chat_messages(
        self,
        inputs: list[dict[str, Any]],
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

        if latest_user_message:
            history_messages.append({"role": "user", "content": latest_user_message})

        passive_style_digest = await PassiveProcessor(
            inputs,
            include_system_intro=False,
        ).process_inputs(self.inference_count)
        full_event_block = self._build_full_event_context(inputs, limit=90)
        context_blob = (
            "Supporting perception context (passive inference format):\n"
            f"{passive_style_digest}\n\n"
            "Full event context window (last 90 events, raw data):\n"
            f"{full_event_block}"
        )
        context_content = self._build_multimodal_user_content(
            prompt=context_blob,
            inputs=inputs,
        )
        context_message = {"role": "user", "content": context_content}
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

    async def feed(self, inputs: list[dict[str, Any]], states: KernelStates):
        if states.phase == Phases.PASSIVE:
            return await self.feed_passive(inputs, states)

        if states.phase == Phases.ACTIVE:
            return await self.feed_active(inputs, states)

        return await self.feed_passive(inputs, states)
