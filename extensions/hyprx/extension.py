from __future__ import annotations

import logging
import os
import time
from importlib import import_module
from typing import Any

from client import HyprXClient
from constants import (
    HYPRX_REPLY_ONLY_TOOLSET,
    HYPRX_REQUIRED_ENV,
    TOOL_TWITTER_POST,
    TOOL_TWITTER_REPLY,
    TOOL_TWITTER_REPOST,
)
from policy import HyprXPolicy
from storage import HyprXStorage
from utils import async_toolify

from hyprchan.core.extensions.executor import ExtensionExecutor
from hyprchan.core.extensions.extension import HyprchanExtension
from hyprchan.core.extensions.storage import ExtensionKV, extension_kv_path
from hyprchan.core.hypraios.hooks.types import HookResult
from hyprchan.core.hypraios.tools.types import ToolSpec


class HyprXExtension(HyprchanExtension):
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.policy = HyprXPolicy.from_env()
        self.kv = ExtensionKV(extension_kv_path("hyprx"))
        self.storage = HyprXStorage(self.kv)
        self._executor: ExtensionExecutor | None = None
        self._tool_snapshot: dict[str, ToolSpec] | None = None
        self._tool_lock_started_at = 0.0
        self._tool_lock_max_age_sec = 120.0
        self._mention_trust_cache: dict[int, bool] = {}

        missing = [
            name for name in HYPRX_REQUIRED_ENV if not os.getenv(name, "").strip()
        ]
        self.enabled = not missing
        if missing:
            self.logger.warning(
                "[cyan]HYPRX[/] Disabled (missing env): %s",
                ", ".join(missing),
            )
            self.client = None
            return

        self.client = HyprXClient(
            api_key=os.getenv("HYPRX_API_KEY", "").strip(),
            api_secret=os.getenv("HYPRX_API_SECRET", "").strip(),
            access_token=os.getenv("HYPRX_ACCESS_TOKEN", "").strip(),
            access_token_secret=os.getenv("HYPRX_ACCESS_TOKEN_SECRET", "").strip(),
        )

    @property
    def executor(self) -> ExtensionExecutor:
        if self._executor is None:
            raise RuntimeError("Executor not initialized")
        return self._executor

    async def on_init(self, executor: ExtensionExecutor) -> None:
        self._executor = executor
        await self.kv.connect()

        if not self.enabled or self.client is None:
            self.logger.info("[cyan]HYPRX[/] Init skipped (extension disabled).")
            return

        self._register_tools()
        self.executor.add_hook("on_ponder", self.on_ponder)  # pyright: ignore[reportArgumentType]
        self.executor.add_hook("on_ai_inference", self.on_ai_inference)  # pyright: ignore[reportArgumentType]
        self.executor.add_hook("on_ai_response", self.on_ai_response)  # pyright: ignore[reportArgumentType]
        self.logger.info(
            "[cyan]HYPRX[/] Ready. Tools: %s",
            ", ".join(self.executor.tool_manager.list_names()),
        )

    async def on_shutdown(self) -> None:
        self._restore_toolbox()
        await self.kv.close()

    def _structured_tool_from_function(
        self,
        *,
        coroutine: Any,
        name: str,
        description: str,
    ) -> Any:
        structured_tool = import_module("langchain_core.tools").StructuredTool
        return structured_tool.from_function(
            coroutine=coroutine,
            name=name,
            description=description,
        )

    def _register_tools(self) -> None:
        self.executor.tool_manager.register(
            ToolSpec(
                name=TOOL_TWITTER_POST,
                tool=self._structured_tool_from_function(
                    coroutine=async_toolify(self._tool_post),
                    name=TOOL_TWITTER_POST,
                    description=(
                        "Post a new short message on X/Twitter. "
                        "Stay in persona and avoid spam."
                    ),
                ),
                priority=15,
            )
        )

        self.executor.tool_manager.register(
            ToolSpec(
                name=TOOL_TWITTER_REPLY,
                tool=self._structured_tool_from_function(
                    coroutine=async_toolify(self._tool_reply),
                    name=TOOL_TWITTER_REPLY,
                    description=(
                        "Reply to a specific X/Twitter tweet by id. "
                        "Use when you intentionally engage with a mention."
                    ),
                ),
                priority=20,
            )
        )

        self.executor.tool_manager.register(
            ToolSpec(
                name=TOOL_TWITTER_REPOST,
                tool=self._structured_tool_from_function(
                    coroutine=async_toolify(self._tool_repost),
                    name=TOOL_TWITTER_REPOST,
                    description=(
                        "Repost (retweet) a tweet by id. "
                        "Use sparingly and only when genuinely aligned."
                    ),
                ),
                priority=10,
            )
        )

    @staticmethod
    def _phase_name(payload: dict[str, object]) -> str:
        phase = payload.get("phase")
        if phase is None:
            return ""
        name = getattr(phase, "name", None)
        if isinstance(name, str):
            return name.upper()
        return str(phase).upper()

    async def on_ponder(self, payload: dict[str, object]) -> HookResult:
        if not self.enabled or self.client is None:
            return HookResult(payload=payload)
        if self._phase_name(payload) != "PASSIVE":
            return HookResult(payload=payload)

        self._restore_toolbox_if_stale()

        inputs: list[dict[str, object]] = []
        raw_inputs = payload.get("inputs", [])
        if isinstance(raw_inputs, list):
            for item in raw_inputs:
                if isinstance(item, dict):
                    inputs.append(dict(item))

        mention_inputs = await self._build_mention_inputs()
        if mention_inputs:
            inputs.extend(mention_inputs)

        autopost_probe = await self._build_autopost_probe_input()
        if autopost_probe is not None:
            inputs.append(autopost_probe)

        return HookResult(payload={**payload, "inputs": inputs}, stop=False)

    async def on_ai_inference(self, payload: dict[str, object]) -> HookResult:
        if not self.enabled:
            return HookResult(payload=payload)

        self._restore_toolbox_if_stale()
        if self._is_stranger_cycle(payload):
            self._lock_to_reply_only()
        else:
            self._restore_toolbox()
        return HookResult(payload=payload, stop=False)

    async def on_ai_response(self, payload: dict[str, object]) -> HookResult:
        if self.enabled:
            self._restore_toolbox()
        return HookResult(payload=payload, stop=False)

    def _is_stranger_cycle(self, payload: dict[str, object]) -> bool:
        raw_inputs = payload.get("inputs", [])
        if not isinstance(raw_inputs, list):
            return False
        for item in raw_inputs:
            if not isinstance(item, dict):
                continue
            if str(item.get("origin", "")).strip().lower() != "hyprx":
                continue
            if str(item.get("channel", "")).strip().lower() != "twitter":
                continue
            if bool(item.get("hyprx_sandbox_stranger", False)):
                return True
        return False

    def _lock_to_reply_only(self) -> None:
        if self._tool_snapshot is not None:
            return

        tool_manager = self.executor.tool_manager
        names = tool_manager.list_names()
        snapshot: dict[str, ToolSpec] = {}
        for name in names:
            spec = tool_manager.get(name)
            if spec is None:
                continue
            snapshot[name] = spec

        if TOOL_TWITTER_REPLY not in snapshot:
            self.logger.warning(
                "[cyan]HYPRX[/] Cannot apply reply-only lock: missing %s",
                TOOL_TWITTER_REPLY,
            )
            return

        for name in names:
            if name in HYPRX_REPLY_ONLY_TOOLSET:
                continue
            tool_manager.unregister(name)

        self._tool_snapshot = snapshot
        self._tool_lock_started_at = time.monotonic()
        self.logger.info(
            "[cyan]HYPRX[/] Reply-only tool lock enabled for stranger cycle."
        )

    def _restore_toolbox_if_stale(self) -> None:
        if self._tool_snapshot is None:
            return
        if (
            time.monotonic() - self._tool_lock_started_at
        ) < self._tool_lock_max_age_sec:
            return
        self.logger.warning("[cyan]HYPRX[/] Restoring stale tool lock snapshot.")
        self._restore_toolbox()

    def _restore_toolbox(self) -> None:
        if self._tool_snapshot is None:
            return

        tool_manager = self.executor.tool_manager
        snapshot = self._tool_snapshot
        tool_manager.clear()
        for spec in snapshot.values():
            tool_manager.register(spec, replace=True)
        self._tool_snapshot = None
        self._tool_lock_started_at = 0.0
        self.logger.info("[cyan]HYPRX[/] Tool lock released.")

    async def _build_mention_inputs(self) -> list[dict[str, object]]:
        if self.client is None:
            return []

        if not await self.storage.should_poll_mentions(
            self.policy.mention_poll_cooldown_sec
        ):
            return []

        since_id = await self.storage.get_last_mention_id()
        mentions = await self.client.fetch_mentions(
            since_id=since_id,
            limit=self.policy.max_mentions_per_poll,
        )
        await self.storage.mark_mentions_polled()
        if not mentions:
            return []

        max_seen = max(item.tweet_id for item in mentions)
        await self.storage.set_last_mention_id(max_seen)

        inputs: list[dict[str, object]] = []
        for mention in mentions:
            if await self.storage.has_replied_to_tweet(mention.tweet_id):
                continue

            trusted = self.policy.is_whitelisted(
                author_id=mention.author_id,
                author_username=mention.author_username,
            )

            if not trusted:
                used = await self.storage.daily_count("stranger_replies")
                if used >= self.policy.max_stranger_replies_per_day:
                    continue
                if not self.policy.should_consider_stranger_reply():
                    continue

            self._mention_trust_cache[int(mention.tweet_id)] = trusted
            author = mention.author_username or "unknown"
            desc = (
                f"X mention from @{author} [TWEET_ID={mention.tweet_id}]: {mention.text}. "
                "If you intentionally respond, use twitter_reply(tweet_id, text). "
                "Stay in your established persona."
            )

            inputs.append(
                {
                    "timestamp": time.time(),
                    "type": "communication_message",
                    "description": desc,
                    "origin": "hyprx",
                    "amplitude": 1.0,
                    "is_user": False,
                    "attention_required": trusted,
                    "channel": "twitter",
                    "twitter_event": "mention",
                    "twitter_tweet_id": int(mention.tweet_id),
                    "twitter_author_id": mention.author_id,
                    "twitter_author_username": mention.author_username,
                    "twitter_trusted": trusted,
                    "hyprx_sandbox_stranger": (not trusted),
                }
            )

        return inputs

    async def _build_autopost_probe_input(self) -> dict[str, object] | None:
        if not await self.storage.should_probe_autopost(
            self.policy.autopost_probe_cooldown_sec
        ):
            return None

        await self.storage.mark_autopost_probe()

        used_posts = await self.storage.daily_count("posts")
        if used_posts >= self.policy.max_posts_per_day:
            return None
        if not self.policy.should_emit_autopost_probe():
            return None

        return {
            "timestamp": time.time(),
            "type": "autonomy_probe",
            "description": (
                "X posting window is open. If you genuinely have a playful or useful thought, "
                "you may post once via twitter_post(text). Keep it in-character and concise. Note that the post will be available and broadcasted to your community."
            ),
            "origin": "hyprx",
            "amplitude": 0.65,
            "is_user": False,
            "channel": "twitter",
            "hyprx_autopost": True,
        }

    async def _tool_post(self, text: str) -> dict[str, object]:
        if self.client is None:
            return {"status": "error", "result": "hyprx is not configured"}

        message = " ".join(str(text).split()).strip()
        if not message:
            return {"status": "invalid", "result": "text is empty"}
        if len(message) > 280:
            return {"status": "invalid", "result": "text exceeds 280 characters"}

        used = await self.storage.daily_count("posts")
        if used >= self.policy.max_posts_per_day:
            return {"status": "skipped", "result": "Daily post cap reached"}

        result = await self.client.post(message)
        await self.storage.claim_daily_quota("posts", self.policy.max_posts_per_day)
        return {
            "status": "success",
            "result": "Posted to X",
            "tweet_id": result.get("tweet_id"),
        }

    async def _tool_reply(self, tweet_id: int, text: str) -> dict[str, object]:
        if self.client is None:
            return {"status": "error", "result": "hyprx is not configured"}

        try:
            target_tweet_id = int(tweet_id)
        except (TypeError, ValueError):
            return {"status": "invalid", "result": "tweet_id is invalid"}

        message = " ".join(str(text).split()).strip()
        if not message:
            return {"status": "invalid", "result": "text is empty"}
        if len(message) > 280:
            return {"status": "invalid", "result": "text exceeds 280 characters"}

        if await self.storage.has_replied_to_tweet(target_tweet_id):
            return {
                "status": "skipped",
                "result": "Reply already sent to this tweet",
            }

        trusted = self._mention_trust_cache.get(target_tweet_id, False)
        if not trusted:
            used = await self.storage.daily_count("stranger_replies")
            if used >= self.policy.max_stranger_replies_per_day:
                return {
                    "status": "skipped",
                    "result": "Daily stranger-reply cap reached",
                }

        result = await self.client.reply(tweet_id=target_tweet_id, text=message)
        if not trusted:
            await self.storage.claim_daily_quota(
                "stranger_replies",
                self.policy.max_stranger_replies_per_day,
            )
        await self.storage.mark_replied_to_tweet(target_tweet_id)
        return {
            "status": "success",
            "result": "Reply posted to X",
            "tweet_id": result.get("tweet_id"),
            "reply_to": target_tweet_id,
        }

    async def _tool_repost(self, tweet_id: int) -> dict[str, object]:
        if self.client is None:
            return {"status": "error", "result": "hyprx is not configured"}

        try:
            target_tweet_id = int(tweet_id)
        except (TypeError, ValueError):
            return {"status": "invalid", "result": "tweet_id is invalid"}

        used = await self.storage.daily_count("posts")
        if used >= self.policy.max_posts_per_day:
            return {"status": "skipped", "result": "Daily post cap reached"}

        await self.client.repost(tweet_id=target_tweet_id)
        await self.storage.claim_daily_quota("posts", self.policy.max_posts_per_day)
        return {
            "status": "success",
            "result": "Reposted on X",
            "tweet_id": target_tweet_id,
        }
