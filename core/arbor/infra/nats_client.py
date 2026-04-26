"""NATS 客户端单例"""
import nats
from nats.aio.client import Client as NATS

client: NATS | None = None


async def connect(url: str) -> None:
    global client
    client = await nats.connect(
        url,
        name="nervus-arbor",
        reconnect_time_wait=2,
        max_reconnect_attempts=-1,
    )


async def disconnect() -> None:
    global client
    if client:
        await client.drain()
        client = None


async def publish(subject: str, data: bytes) -> None:
    if client is None:
        raise RuntimeError("NATS 未连接")
    await client.publish(subject, data)
