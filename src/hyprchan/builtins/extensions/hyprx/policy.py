from __future__ import annotations

import os
import random
from dataclasses import dataclass


def _env_int(name: str, default: int, *, min_value: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, value)


def _env_float(
    name: str,
    default: float,
    *,
    min_value: float = 0.0,
    max_value: float = 1.0,
) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


@dataclass(slots=True)
class HyprXPolicy:
    max_posts_per_day: int
    max_stranger_replies_per_day: int
    stranger_reply_probability: float
    mention_poll_cooldown_sec: float
    autopost_probe_cooldown_sec: float
    autopost_probe_probability: float
    max_mentions_per_poll: int
    whitelist_ids: set[int]
    whitelist_usernames: set[str]

    @classmethod
    def from_env(cls) -> "HyprXPolicy":
        whitelist_ids: set[int] = set()
        whitelist_usernames: set[str] = set()
        raw_whitelist = os.getenv("HYPRX_WHITELIST", "")
        for token in raw_whitelist.split(","):
            cleaned = token.strip()
            if not cleaned:
                continue
            if cleaned.isdigit():
                whitelist_ids.add(int(cleaned))
                continue
            whitelist_usernames.add(cleaned.lower().lstrip("@"))

        return cls(
            max_posts_per_day=_env_int("HYPRX_MAX_POSTS_PER_DAY", 2, min_value=0),
            max_stranger_replies_per_day=_env_int(
                "HYPRX_MAX_STRANGER_REPLIES_PER_DAY", 3, min_value=0
            ),
            stranger_reply_probability=_env_float(
                "HYPRX_STRANGER_REPLY_PROBABILITY", 0.10
            ),
            mention_poll_cooldown_sec=_env_float(
                "HYPRX_MENTION_POLL_COOLDOWN_SEC",
                600.0,
                min_value=30.0,
                max_value=86400.0,
            ),
            autopost_probe_cooldown_sec=_env_float(
                "HYPRX_AUTOPOST_PROBE_COOLDOWN_SEC",
                10800.0,
                min_value=60.0,
                max_value=86400.0,
            ),
            autopost_probe_probability=_env_float(
                "HYPRX_AUTOPOST_PROBE_PROBABILITY",
                0.20,
            ),
            max_mentions_per_poll=_env_int(
                "HYPRX_MAX_MENTIONS_PER_POLL",
                8,
                min_value=1,
            ),
            whitelist_ids=whitelist_ids,
            whitelist_usernames=whitelist_usernames,
        )

    def is_whitelisted(
        self,
        *,
        author_id: int | None,
        author_username: str | None,
    ) -> bool:
        if author_id is not None and author_id in self.whitelist_ids:
            return True
        if author_username:
            normalized = author_username.strip().lower().lstrip("@")
            if normalized and normalized in self.whitelist_usernames:
                return True
        return False

    def should_consider_stranger_reply(self) -> bool:
        return random.random() <= self.stranger_reply_probability

    def should_emit_autopost_probe(self) -> bool:
        return random.random() <= self.autopost_probe_probability
