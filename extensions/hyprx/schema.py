from __future__ import annotations

from typing import TypedDict


class TwitterPostInput(TypedDict):
    text: str


class TwitterReplyInput(TypedDict):
    tweet_id: int
    text: str


class TwitterRepostInput(TypedDict):
    tweet_id: int
