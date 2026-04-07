import time
from asyncio import Queue, QueueEmpty
from collections import defaultdict
from typing import Any

from aiogram.types import Message
from media import TelegramMediaStore
from storage import DataStorage  # pyright: ignore[reportImplicitRelativeImport]

from core.hypraios.hooks import (
    AiInferencePayload,  # TODO: Soon this one will be changed
)
from hyprchan import ExtensionExecutor, HookResult


class HyprgramHandler:
    def __init__(
        self,
        storage: DataStorage,
        executor: ExtensionExecutor,
        media_store: TelegramMediaStore,
        *,
        admin_id: int | None = None,
    ) -> None:
        self.storage = storage
        self.admin_id = admin_id
        self.executor = executor
        self.media_store = media_store
        self.pending_unsandboxed = Queue[dict[str, Any]]()
        self._recent_chat_targets: dict[int, tuple[int, float]] = {}
        self._target_ttl_sec = 300.0

    async def on_message(self, message: Message):
        if not message.from_user:
            await message.answer("You must be logged in to talk to hyprchan.")
            return

        images = await self.media_store.extract_images(message)

        if (
            self.admin_id
            and message.from_user.id == self.admin_id
        ):
            payload_metadata: dict[str, object] = {
                "channel": "telegram",
                "chat_id": message.chat.id,
                "message_id": message.message_id,
            }
            if images:
                payload_metadata["images"] = images
            await self.executor.emit_signal(
                event_type="communication_message",
                description=self.form_message([message]),
                origin="communication_controller",
                amplitude=1.0,
                force_active=True,
                metadata=payload_metadata,
            )
            return

        trusted = await self.storage.is_trusted_user(message.from_user.id)

        if not trusted:
            await self.pending_unsandboxed.put({"message": message, "images": images})
        else:
            payload_metadata = {
                "channel": "telegram",
                "chat_id": message.chat.id,
                "message_id": message.message_id,
                "trusted": True,
            }
            if images:
                payload_metadata["images"] = images
            await self.executor.emit_signal(
                event_type="communication_message",
                description=self.form_message([message]),
                origin="hyprgram",
                amplitude=1.0,
                metadata=payload_metadata,
            )

    def form_message(self, messages: list[Message]) -> str:
        chats = defaultdict(list)  # Chat name - list of messages

        for message in messages:
            user = (
                message.from_user.username or message.from_user.full_name
                if message.from_user
                else "Unknown"
            )
            chats[f"{message.chat.title} [ID={message.chat.id}]"].append(
                f"{user} [MESSAGE_ID={message.message_id}]: {self._message_content_preview(message)}"
            )

        if not chats:
            return ""

        tool_hint = (
            "Telegram channel active. You can respond via telegram_reply_message(chat_id, message_id, text) "
            "or send a fresh message via telegram_send_message(chat_id, text, source_message_id)."
        )

        return "\n".join(
            [f"Chat {chat}: {', '.join(messages)}" for chat, messages in chats.items()]
            + [tool_hint]
        )

    @staticmethod
    def _message_content_preview(message: Message) -> str:
        text = str(message.text or message.caption or "").strip()
        if text:
            return text
        if message.photo:
            return "[image uploaded]"
        if message.document:
            mime = str(message.document.mime_type or "").strip().lower()
            if mime.startswith("image/"):
                return "[image document uploaded]"
        return "[non-text message]"

    def _remember_chat_target(self, chat_id: int, message_id: int) -> None:
        self._recent_chat_targets[chat_id] = (message_id, time.monotonic())

    def latest_target_for_chat(self, chat_id: int) -> int | None:
        target = self._recent_chat_targets.get(chat_id)
        if target is None:
            return None
        message_id, ts = target
        if (time.monotonic() - ts) > self._target_ttl_sec:
            self._recent_chat_targets.pop(chat_id, None)
            return None
        return message_id

    async def before_inference(self, payload: AiInferencePayload) -> HookResult:
        inputs_raw = payload.get("inputs", [])
        inputs: list[dict[str, object]] = []
        if isinstance(inputs_raw, list):
            for item in inputs_raw:
                if not isinstance(item, dict):
                    continue
                channel = item.get("channel")
                event_type = item.get("type")
                chat_id = item.get("chat_id")
                message_id = item.get("message_id")

                if (
                    channel == "telegram"
                    and event_type == "communication_message"
                    and isinstance(chat_id, int)
                    and isinstance(message_id, int)
                ):
                    if await self.storage.has_replied_to_message(chat_id, message_id):
                        continue
                    self._remember_chat_target(chat_id, message_id)

                inputs.append(item)

        if not self.pending_unsandboxed.empty():
            messages = []
            images: list[dict[str, Any]] = []
            while not self.pending_unsandboxed.empty():
                try:
                    queued = self.pending_unsandboxed.get_nowait()
                    if not isinstance(queued, dict):
                        continue
                    message = queued.get("message")
                    if not isinstance(message, Message):
                        continue
                    if await self.storage.has_replied_to_message(
                        message.chat.id, message.message_id
                    ):
                        continue
                    self._remember_chat_target(message.chat.id, message.message_id)
                    messages.append(message)
                    queued_images = queued.get("images")
                    if isinstance(queued_images, list):
                        for item in queued_images:
                            if isinstance(item, dict):
                                images.append(item)
                except QueueEmpty:
                    break
            if messages:
                new_input: dict[str, object] = {
                    "timestamp": time.monotonic(),
                    "type": "communication_message",
                    "description": self.form_message(messages),
                    "origin": "hyprgram",
                    "amplitude": 1.0,
                    "is_user": False,
                    "channel": "telegram",
                }
                if images:
                    new_input["images"] = images
                inputs.append(new_input)

        outbound_context = await self.storage.build_outbound_context(limit=4)
        if outbound_context:
            outbound_input: dict[str, object] = {
                "timestamp": time.monotonic(),
                "type": "internal_extension_context",
                "description": outbound_context,
                "origin": "hyprgram",
                "amplitude": 0.05,
                "is_user": False,
                "channel": "telegram",
            }
            inputs.append(outbound_input)

        return HookResult(payload={**payload, "inputs": inputs}, stop=False)
