from pydantic import BaseModel, Field


class TelegramTrustedUserInput(BaseModel):
    user_id: int = Field(description="Telegram user ID.")


class TelegramSendMessageInput(BaseModel):
    chat_id: int = Field(description="Telegram chat ID.")
    text: str = Field(min_length=1, max_length=4000)
    source_message_id: int | None = Field(
        default=None,
        description=(
            "Optional incoming telegram MESSAGE_ID this outbound message handles. "
            "Set when answering a specific user message without threaded reply."
        ),
    )


class TelegramReplyMessageInput(BaseModel):
    chat_id: int = Field(description="Telegram chat ID.")
    message_id: int = Field(description="Telegram message ID to reply to.")
    text: str = Field(min_length=1, max_length=4000)
