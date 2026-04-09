from __future__ import annotations

from dataclasses import dataclass

import tiktoken


@dataclass(frozen=True)
class BiasProfile:
    name: str
    anchor_v: float
    anchor_e: float
    term_weights: dict[str, float]


class StateLogitBiasBuilder:
    """
    Builds dynamic token-level logit bias from state scalars.

    This follows the documented style-bias direction where bias strength is
    proportional to state conditions, while keeping all values damped.
    """

    _PROFILES = {
        "sparkly": BiasProfile(
            name="sparkly",
            anchor_v=0.35,
            anchor_e=0.85,
            term_weights={
                "kawaii": 0.30,
                "sparkle": 0.24,
                "cheerful": 0.22,
                "bright": 0.20,
                "chibi": 0.16,
                "shimmer": 0.14,
                "giggle": 0.12,
                "upbeat": 0.12,
                "glowy": 0.10,
                "dramatic": -0.10,
                "bleak": -0.16,
                "grim": -0.14,
            },
        ),
        "cheerful": BiasProfile(
            name="cheerful",
            anchor_v=0.18,
            anchor_e=0.65,
            term_weights={
                "kawaii": 0.18,
                "bright": 0.16,
                "cheerful": 0.14,
                "sparkle": 0.12,
                "soft": 0.10,
                "cute": 0.10,
                "playful": 0.08,
                "dramatic": -0.06,
                "bleak": -0.10,
            },
        ),
        "irritated": BiasProfile(
            name="irritated",
            anchor_v=-0.30,
            anchor_e=0.55,
            term_weights={
                "terse": 0.14,
                "flat": 0.10,
                "stern": 0.10,
                "kawaii": -0.12,
                "sparkle": -0.12,
                "cheerful": -0.10,
                "bleak": 0.06,
            },
        ),
        "angry": BiasProfile(
            name="angry",
            anchor_v=-0.65,
            anchor_e=0.60,
            term_weights={
                "sharp": 0.18,
                "stern": 0.14,
                "blunt": 0.12,
                "kawaii": -0.18,
                "sparkle": -0.18,
                "cheerful": -0.14,
                "bleak": 0.10,
            },
        ),
    }

    def __init__(self) -> None:
        self._encoding_cache: dict[str, tiktoken.Encoding] = {}

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def _pick_profile(self, v: float, e: float) -> BiasProfile | None:
        if v > 0.2 and e > 0.75:
            return self._PROFILES["sparkly"]
        if v > 0.1 and e > 0.55:
            return self._PROFILES["cheerful"]
        if v < -0.6:
            return self._PROFILES["angry"]
        if v < -0.25:
            return self._PROFILES["irritated"]
        return None

    def _profile_gain(self, profile: BiasProfile, v: float, e: float) -> float:
        if profile.anchor_v >= 0:
            signal = max(v, 0.0) * max(e, 0.0)
            anchor = profile.anchor_v * profile.anchor_e
        else:
            signal = max(-v, 0.0) * max(e, 0.0)
            anchor = max(-profile.anchor_v, 0.0) * profile.anchor_e

        if anchor <= 1e-9:
            return 0.0

        return self._clamp(signal / anchor, 0.0, 1.5)

    def build_lexical_bias(self, *, v: float, e: float) -> tuple[str, dict[str, float]]:
        profile = self._pick_profile(v, e)
        if profile is None:
            return "neutral", {}

        gain = self._profile_gain(profile, v, e)
        scaled = {
            term: self._clamp(weight * gain, -1.0, 1.0)
            for term, weight in profile.term_weights.items()
        }
        return profile.name, scaled

    def _get_encoding(self, model: str) -> tiktoken.Encoding:
        if model in self._encoding_cache:
            return self._encoding_cache[model]

        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            try:
                encoding = tiktoken.get_encoding("o200k_base")
            except KeyError:
                encoding = tiktoken.get_encoding("cl100k_base")

        self._encoding_cache[model] = encoding
        return encoding

    def build_token_logit_bias(
        self,
        *,
        v: float,
        e: float,
        model: str,
        max_abs_bias: int = 20,
    ) -> tuple[str, dict[str, int], dict[str, float]]:
        profile_name, lexical = self.build_lexical_bias(v=v, e=e)
        if not lexical:
            return profile_name, {}, {}

        encoding = self._get_encoding(model)
        token_bias: dict[str, int] = {}
        for term, weight in lexical.items():
            token_ids = encoding.encode(term)
            if not token_ids:
                continue

            token_int_bias = int(
                round(self._clamp(weight * 30.0, -max_abs_bias, max_abs_bias))
            )
            if token_int_bias == 0:
                continue

            for token_id in token_ids:
                token_bias[str(token_id)] = token_int_bias

        return profile_name, token_bias, lexical
