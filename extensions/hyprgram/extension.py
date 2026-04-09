import asyncio
import os
from logging import Logger

from aiogram import Bot, Dispatcher
from ascender.core import inject
from handler import HyprgramHandler
from langchain_core.tools import StructuredTool
from media import TelegramMediaStore
from schema import (
    TelegramReplyMessageInput,
    TelegramSendMessageInput,
    TelegramTrustedUserInput,
)
from storage import DataStorage
from utils import async_toolify

from hyprchan.core.extensions.executor import ExtensionExecutor
from hyprchan.core.extensions.extension import HyprchanExtension
from hyprchan.core.extensions.storage import ExtensionKV, extension_kv_path
from hyprchan.core.extensions.workspace import get_extension_data_dir
from hyprchan.core.hypraios.tools.types import ToolSpec


class HyprgramExtension(HyprchanExtension):
    logger: Logger = inject("ASC_LOGGER")

    def __init__(self) -> None:
        self.bot_token = os.getenv("HYPRGRAM_BOT_TOKEN", None)

        if not self.bot_token:
            self.logger.critical(
                "[cyan]HYPRGRAM[/] Hyprgram bot token not found. Telegram extension is disabled."
            )
            return

        self.bot_username = os.getenv("HYPRGRAM_BOT_USERNAME", None)
        self.bot_debug_channel = os.getenv("HYPRGRAM_BOT_DEBUG_CHANNELID", None)

        if not self.bot_username:
            self.logger.info("[cyan]HYPRGRAM[/] Hyprgram bot username not found")

        self.dispatcher = Dispatcher()
        self.bot = Bot(self.bot_token)

        self.kv = ExtensionKV(extension_kv_path("hyprgram"))
        self.storage = DataStorage(self.kv)
        self.media_store = TelegramMediaStore(
            bot=self.bot,
            root_dir=get_extension_data_dir("hyprgram") / "incoming_images",
        )

        self.__executor = None
        self._polling_task: asyncio.Task[None] | None = None

    async def on_init(self, executor: ExtensionExecutor) -> None:
        self.logger.info("[cyan]HYPRGRAM[/] Hyprgram extension initialized")
        await self.kv.connect()
        self.__executor = executor

        self.handler = HyprgramHandler(
            self.storage,
            self.executor,
            self.media_store,
            admin_id=int(self.bot_debug_channel) if self.bot_debug_channel else None,
        )

        self._polling_task = asyncio.create_task(
            self.dispatcher.start_polling(self.bot, handle_signals=False)
        )
        self._polling_task.add_done_callback(self._on_polling_done)

        if self.bot_debug_channel:
            await self.bot.send_message(int(self.bot_debug_channel), "Hypr-chan is up!")

        self.executor.tool_manager.register(
            ToolSpec(
                name="telegram_add_trusted_user",
                tool=StructuredTool.from_function(
                    coroutine=async_toolify(
                        self.storage.add_trusted_user,
                        on_success=lambda r: {
                            "status": "success",
                            "result": "Successfully added trusted user",
                        },
                    ),
                    name="telegram_add_trusted_user",
                    description="Allow a specific telegram user ID to message you in telegram & bother you...",
                    args_schema=TelegramTrustedUserInput,
                ),
            )
        )

        self.executor.tool_manager.register(
            ToolSpec(
                name="telegram_remove_trusted_user",
                tool=StructuredTool.from_function(
                    coroutine=async_toolify(
                        self.storage.remove_trusted_user,
                        on_success=lambda r: {
                            "status": "success",
                            "result": "Trusted user removed",
                        },
                    ),
                    name="telegram_remove_trusted_user",
                    description="Remove a telegram user ID from the trusted list (they cannot message you anymore).",
                    args_schema=TelegramTrustedUserInput,
                ),
            )
        )

        self.executor.tool_manager.register(
            ToolSpec(
                name="telegram_send_message",
                tool=StructuredTool.from_function(
                    coroutine=async_toolify(self._send_message),
                    name="telegram_send_message",
                    description=(
                        "Send a message to a telegram chat. "
                        "Use chat_id to target the chat. "
                        "When responding to a specific incoming message, pass source_message_id."
                    ),
                    args_schema=TelegramSendMessageInput,
                ),
            )
        )

        self.executor.tool_manager.register(
            ToolSpec(
                name="telegram_reply_message",
                tool=StructuredTool.from_function(
                    coroutine=async_toolify(self._reply_message),
                    name="telegram_reply_message",
                    description=(
                        "Reply to a specific telegram message in a chat using chat_id "
                        "and message_id."
                    ),
                    args_schema=TelegramReplyMessageInput,
                ),
            )
        )

        self.logger.info(
            "[cyan]HYPRGRAM[/] Registered tools: %s",
            ", ".join(self.executor.tool_manager.list_names()),
        )

        self.dispatcher.message()(self.handler.on_message)
        self.executor.add_hook("on_ai_inference", self.handler.before_inference)  # pyright: ignore[reportArgumentType]

    @property
    def executor(self) -> ExtensionExecutor:
        if not self.__executor:
            raise RuntimeError("Executor not initialized")
        return self.__executor

    async def on_shutdown(self) -> None:
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        self._polling_task = None
        await self.dispatcher.stop_polling()
        await self.kv.close()

    def _on_polling_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        self.logger.exception("[cyan]HYPRGRAM[/] Polling loop crashed: %s", error)

    async def _send_message(
        self, chat_id: int, text: str, source_message_id: int | None = None
    ) -> dict[str, object]:
        if source_message_id is None:
            source_message_id = self.handler.latest_target_for_chat(chat_id)
        if (
            isinstance(source_message_id, int)
            and await self.storage.has_replied_to_message(chat_id, source_message_id)
        ):
            return {
                "status": "skipped",
                "result": f"Message already handled for source MESSAGE_ID={source_message_id}",
            }

        if not await self.storage.should_send_message(chat_id, text):
            return {
                "status": "skipped",
                "result": "Duplicate message blocked by anti-spam guard",
            }
        await self.bot.send_message(chat_id=chat_id, text=text)
        await self.storage.remember_outbound(
            chat_id=chat_id,
            text=text,
            mode="send",
            source_message_id=source_message_id,
        )
        return {
            "status": "success",
            "result": "Telegram message sent",
            "source_message_id": source_message_id,
        }

    async def _reply_message(
        self, chat_id: int, message_id: int, text: str
    ) -> dict[str, object]:
        if await self.storage.has_replied_to_message(chat_id, message_id):
            return {
                "status": "skipped",
                "result": "Reply already sent to this message_id",
            }
        await self.bot.send_message(
            chat_id=chat_id, text=text, reply_to_message_id=message_id
        )
        await self.storage.remember_outbound(
            chat_id=chat_id,
            text=text,
            mode="reply",
            source_message_id=message_id,
        )
        return {
            "status": "success",
            "result": "Telegram reply sent",
            "source_message_id": message_id,
        }
