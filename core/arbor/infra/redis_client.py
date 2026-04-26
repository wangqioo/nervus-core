"""Redis 客户端单例"""
import redis.asyncio as aioredis

client: aioredis.Redis | None = None


async def connect(url: str) -> None:
    global client
    client = await aioredis.from_url(url, encoding="utf-8", decode_responses=True)


async def disconnect() -> None:
    global client
    if client:
        await client.aclose()
        client = None


async def get(key: str):
    if client is None:
        raise RuntimeError("Redis 未连接")
    return await client.get(key)


async def set(key: str, value: str, ttl: int | None = None) -> None:
    if client is None:
        raise RuntimeError("Redis 未连接")
    if ttl:
        await client.setex(key, ttl, value)
    else:
        await client.set(key, value)
