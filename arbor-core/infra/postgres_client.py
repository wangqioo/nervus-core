"""PostgreSQL 客户端单例"""
import asyncpg

pool: asyncpg.Pool | None = None


async def connect(url: str) -> None:
    global pool
    pool = await asyncpg.create_pool(url, min_size=2, max_size=10)


async def disconnect() -> None:
    global pool
    if pool:
        await pool.close()
        pool = None
