from typing import Any
from core.hypraios.constants import Phases
from core.hypraios.linguistic.inference_engine import InferenceEngine
from core.hypraios.linguistic.logit_bias import StateLogitBiasBuilder
from core.hypraios.linguistic.passive_inference import PassiveProcessor
from core.hypraios.linguistic.persona_memory import PersonaMemory
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
        self.last_bias_profile = "neutral"
        self.last_lexical_bias: dict[str, float] = {}
        self._passive_system_intro_sent = False

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
            "- Keep behavior override-friendly and operator-safe."
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

    async def _run_inference(self, prompt: str, *, mode: str, states: KernelStates):
        system_prompt = self._build_system_prompt(mode)

        bias_profile, token_logit_bias, lexical_bias = (
            self.logit_bias_builder.build_token_logit_bias(
                v=states.v.value,
                e=states.e.value,
                model=self.inference_engine.model,
            )
        )
        self.last_bias_profile = bias_profile
        self.last_lexical_bias = lexical_bias

        result = await self.inference_engine.infer(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature.value,
            top_p=self.top_p.value,
            max_output_tokens=400,
            logit_bias=token_logit_bias,
        )
        self.inference_count += 1
        self.persona_memory.remember_turn(prompt, result.output)

        return {
            "input": prompt,
            "output": result.output,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
            "bias_profile": self.last_bias_profile,
            "token_bias_count": len(token_logit_bias),
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
        return await self._run_inference(passive_prompt, mode="PASSIVE", states=states)

    async def feed_active(self, inputs: list[dict[str, Any]], states: KernelStates):
        if not inputs:
            return None

        self._update_sampling_params(states)
        user_signals = [
            item.get("description", "")
            for item in inputs
            if item.get("origin") == "communication_controller"
        ]

        if user_signals:
            prompt = "\n".join(str(signal) for signal in user_signals[-3:])
        else:
            prompt = await PassiveProcessor(inputs).process_inputs(self.inference_count)

        return await self._run_inference(prompt, mode="ACTIVE", states=states)

    async def feed(self, inputs: list[dict[str, Any]], states: KernelStates):
        if states.phase == Phases.PASSIVE:
            return await self.feed_passive(inputs, states)

        if states.phase == Phases.ACTIVE:
            return await self.feed_active(inputs, states)

        return await self.feed_passive(inputs, states)
