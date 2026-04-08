from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Mention:
    tweet_id: int
    author_id: int | None
    author_username: str | None
    text: str


class HyprXClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_token_secret: str,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token
        self._access_token_secret = access_token_secret
        self._api: Any = None
        self._client_v2: Any = None
        self._account_id: int | None = None
        self._account_username: str | None = None

    @property
    def account_username(self) -> str | None:
        return self._account_username

    def _ensure_api(self) -> Any:
        if self._api is not None:
            return self._api

        tweepy = importlib.import_module("tweepy")
        auth = tweepy.OAuth1UserHandler(
            self._api_key,
            self._api_secret,
            self._access_token,
            self._access_token_secret,
        )
        api = tweepy.API(auth)
        me = api.verify_credentials()
        if me is None:
            raise RuntimeError("Unable to verify X credentials.")

        account_id = getattr(me, "id", None)
        if isinstance(account_id, int):
            self._account_id = account_id

        username = getattr(me, "screen_name", None)
        if isinstance(username, str) and username.strip():
            self._account_username = username.strip().lstrip("@")

        self._api = api
        return self._api

    def _ensure_client_v2(self) -> Any:
        if self._client_v2 is not None:
            return self._client_v2

        tweepy = importlib.import_module("tweepy")
        client = tweepy.Client(
            consumer_key=self._api_key,
            consumer_secret=self._api_secret,
            access_token=self._access_token,
            access_token_secret=self._access_token_secret,
            wait_on_rate_limit=True,
        )
        me = client.get_me(user_auth=True)
        data = getattr(me, "data", None)
        if data is not None:
            user_id = getattr(data, "id", None)
            username = getattr(data, "username", None)
            if isinstance(user_id, int):
                self._account_id = user_id
            if isinstance(username, str) and username.strip():
                self._account_username = username.strip().lstrip("@")

        self._client_v2 = client
        return self._client_v2

    async def fetch_mentions(
        self,
        *,
        since_id: int | None = None,
        limit: int = 20,
    ) -> list[Mention]:
        return await asyncio.to_thread(
            self._fetch_mentions_sync,
            since_id=since_id,
            limit=limit,
        )

    def _fetch_mentions_sync(
        self,
        *,
        since_id: int | None = None,
        limit: int = 20,
    ) -> list[Mention]:
        api = self._ensure_api()
        count = max(1, min(limit, 200))
        timeline = api.mentions_timeline(
            since_id=since_id,
            count=count,
            tweet_mode="extended",
        )

        mentions: list[Mention] = []
        for status in reversed(timeline):
            raw_id = getattr(status, "id", None)
            if not isinstance(raw_id, int):
                continue

            user = getattr(status, "user", None)
            author_id = getattr(user, "id", None)
            if not isinstance(author_id, int):
                author_id = None

            username = getattr(user, "screen_name", None)
            if not isinstance(username, str):
                username = None

            text = getattr(status, "full_text", None)
            if not isinstance(text, str):
                text = str(getattr(status, "text", "")).strip()
            text = text.strip()

            mentions.append(
                Mention(
                    tweet_id=raw_id,
                    author_id=author_id,
                    author_username=username,
                    text=text,
                )
            )

        return mentions

    async def post(self, text: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._post_sync, text)

    def _post_sync(self, text: str) -> dict[str, Any]:
        try:
            api = self._ensure_api()
            status = api.update_status(status=text)
            tweet_id = getattr(status, "id", None)
        except Exception:
            client = self._ensure_client_v2()
            response = client.create_tweet(text=text, user_auth=True)
            data = getattr(response, "data", None)
            tweet_id = data.get("id") if isinstance(data, dict) else None

        return {
            "tweet_id": tweet_id,
            "text": text,
        }

    async def reply(self, *, tweet_id: int, text: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._reply_sync, tweet_id=tweet_id, text=text)

    def _reply_sync(self, *, tweet_id: int, text: str) -> dict[str, Any]:
        try:
            api = self._ensure_api()
            status = api.update_status(
                status=text,
                in_reply_to_status_id=tweet_id,
                auto_populate_reply_metadata=True,
            )
            created_id = getattr(status, "id", None)
        except Exception:
            client = self._ensure_client_v2()
            response = client.create_tweet(
                text=text,
                in_reply_to_tweet_id=tweet_id,
                user_auth=True,
            )
            data = getattr(response, "data", None)
            created_id = data.get("id") if isinstance(data, dict) else None

        return {
            "tweet_id": created_id,
            "reply_to": tweet_id,
            "text": text,
        }

    async def repost(self, *, tweet_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._repost_sync, tweet_id=tweet_id)

    def _repost_sync(self, *, tweet_id: int) -> dict[str, Any]:
        status_id: int | None = None
        try:
            api = self._ensure_api()
            status = api.retweet(tweet_id)
            status_id = getattr(status, "id", None)
        except Exception:
            client = self._ensure_client_v2()
            if self._account_id is None:
                me = client.get_me(user_auth=True)
                data = getattr(me, "data", None)
                user_id = getattr(data, "id", None)
                if isinstance(user_id, int):
                    self._account_id = user_id
            if self._account_id is None:
                raise RuntimeError("Unable to resolve account id for repost")
            response = client.retweet(self._account_id, tweet_id, user_auth=True)
            data = getattr(response, "data", None)
            if isinstance(data, dict):
                reposted = data.get("retweeted")
                status_id = tweet_id if reposted else None

        return {
            "tweet_id": tweet_id,
            "status_id": status_id,
        }
