from ascender.core import LifecycleService
from redis.asyncio import Redis


class RedisLifecycle(LifecycleService):
    client: Redis | None

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self.client = None

    async def on_shutdown(self):
        self.client = await Redis.from_url(self.url)

    async def on_startup(self):
        if self.client:
            await self.client.close()

    def __getattr__(self, name):
        return getattr(self.client, name)

    def __getitem__(self, name):
        if self.client:
            return self.client[name]

        raise ConnectionError("Redis client not initialized")


def provideRedis(url: str = "redis://localhost:6379"):
    return {"provide": Redis, "use_factory": lambda: RedisLifecycle(url)}
