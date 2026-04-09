from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import Message, PhotoSize


class TelegramMediaStore:
    def __init__(self, bot: Bot, root_dir: Path) -> None:
        self._bot = bot
        self._root_dir = root_dir
        self._root_dir.mkdir(parents=True, exist_ok=True)

    async def extract_images(self, message: Message) -> list[dict[str, Any]]:
        image_payloads: list[dict[str, Any]] = []

        best_photo = self._pick_best_photo(message.photo)
        if best_photo is not None:
            saved = await self._download_file(
                file_id=best_photo.file_id,
                filename=f"chat{message.chat.id}_msg{message.message_id}_photo.jpg",
            )
            if saved is not None:
                payload: dict[str, Any] = {
                    "path": str(saved),
                    "mime": "image/jpeg",
                    "kind": "telegram_photo",
                }
                if best_photo.width:
                    payload["width"] = int(best_photo.width)
                if best_photo.height:
                    payload["height"] = int(best_photo.height)
                image_payloads.append(payload)

        document = message.document
        if document and document.file_id:
            document_mime = str(document.mime_type or "").strip().lower()
            if document_mime.startswith("image/"):
                suffix = self._suffix_for_mime(document_mime) or ".img"
                saved = await self._download_file(
                    file_id=document.file_id,
                    filename=f"chat{message.chat.id}_msg{message.message_id}_doc{suffix}",
                )
                if saved is not None:
                    image_payloads.append(
                        {
                            "path": str(saved),
                            "mime": document_mime or "image/jpeg",
                            "kind": "telegram_document",
                        }
                    )

        return image_payloads

    @staticmethod
    def _pick_best_photo(items: list[PhotoSize] | None) -> PhotoSize | None:
        if not items:
            return None
        return max(items, key=lambda photo: int(photo.file_size or 0))

    async def _download_file(self, *, file_id: str, filename: str) -> Path | None:
        try:
            file_info = await self._bot.get_file(file_id)
        except Exception:
            return None

        target_path = self._root_dir / filename
        try:
            await self._bot.download(file_info, destination=target_path)
        except Exception:
            return None
        return target_path

    @staticmethod
    def _suffix_for_mime(mime: str) -> str:
        guessed = mimetypes.guess_extension(mime)
        if isinstance(guessed, str) and guessed.strip():
            return guessed
        return ""
