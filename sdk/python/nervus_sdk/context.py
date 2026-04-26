"""
Context Graph — Redis 工作记忆封装
所有 App 共享的当下状态存储
"""

from __future__ import annotations
import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("nervus.context")

# TTL 规则（秒）
_TTL_MAP = {
    "temporal.": 6 * 3600,     # 6 小时
    "physical.": 24 * 3600,    # 24 小时
    "cognitive.": 12 * 3600,   # 12 小时
    "social.": 12 * 3600,      # 12 小时
    "travel.": 7 * 24 * 3600,  # 7 天
    "_app.": None,              # App 自定义
}

_DEFAULT_TTL = 24 * 3600

_redis: aioredis.Redis | None = None
_KEY_PREFIX = "context:user:"


async def connect(redis_url: str) -> None:
    global _redis
    _redis = await aioredis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        retry_on_timeout=True,
    )
    logger.info(f"Context Graph 已连接: {redis_url}")


async def disconnect() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def _full_key(field: str) -> str:
    return f"{_KEY_PREFIX}{field}"


def _get_ttl(field: str) -> int | None:
    for prefix, ttl in _TTL_MAP.items():
        if field.startswith(prefix):
            return ttl
    return _DEFAULT_TTL


class Context:
    """
    Context Graph 操作接口。
    所有方法均为 async classmethod，可直接调用：
        await Context.set("physical.last_meal", "2026-04-20T12:41:00Z")
        value = await Context.get("physical.calorie_remaining")
    """

    @classmethod
    async def get(cls, field: str, default: Any = None) -> Any:
        """读取 Context 字段"""
        if _redis is None:
            raise RuntimeError("Context Graph 未连接")
        raw = await _redis.get(_full_key(field))
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    @classmethod
    async def set(cls, field: str, value: Any, ttl: int | None = None) -> None:
        """写入 Context 字段（自动设置 TTL）"""
        if _redis is None:
            raise RuntimeError("Context Graph 未连接")
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        effective_ttl = ttl if ttl is not None else _get_ttl(field)
        if effective_ttl:
            await _redis.setex(_full_key(field), effective_ttl, serialized)
        else:
            await _redis.set(_full_key(field), serialized)
        logger.debug(f"Context.set: {field} = {value} (TTL={effective_ttl}s)")

    @classmethod
    async def delete(cls, field: str) -> None:
        if _redis is None:
            raise RuntimeError("Context Graph 未连接")
        await _redis.delete(_full_key(field))

    @classmethod
    async def get_namespace(cls, namespace: str) -> dict[str, Any]:
        """
        读取某命名空间下所有字段。
        例：await Context.get_namespace("physical") 返回所有 physical.* 字段
        """
        if _redis is None:
            raise RuntimeError("Context Graph 未连接")
        pattern = _full_key(f"{namespace}.*")
        keys = await _redis.keys(pattern)
        if not keys:
            return {}
        values = await _redis.mget(*keys)
        prefix_len = len(_full_key(f"{namespace}."))
        result = {}
        for key, val in zip(keys, values):
            short_key = key[prefix_len:]
            if val is not None:
                try:
                    result[short_key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    result[short_key] = val
        return result

    @classmethod
    async def increment(cls, field: str, delta: float = 1.0) -> float:
        """原子递增数值字段"""
        if _redis is None:
            raise RuntimeError("Context Graph 未连接")
        key = _full_key(field)
        result = await _redis.incrbyfloat(key, delta)
        ttl = _get_ttl(field)
        if ttl:
            await _redis.expire(key, ttl)
        return float(result)

    @classmethod
    async def push_list(cls, field: str, value: Any, max_len: int = 50) -> None:
        """向列表字段追加元素（自动截断）"""
        if _redis is None:
            raise RuntimeError("Context Graph 未连接")
        key = _full_key(field)
        await _redis.lpush(key, json.dumps(value, default=str))
        await _redis.ltrim(key, 0, max_len - 1)
        ttl = _get_ttl(field)
        if ttl:
            await _redis.expire(key, ttl)

    @classmethod
    async def get_list(cls, field: str) -> list[Any]:
        """读取列表字段"""
        if _redis is None:
            raise RuntimeError("Context Graph 未连接")
        items = await _redis.lrange(_full_key(field), 0, -1)
        result = []
        for item in items:
            try:
                result.append(json.loads(item))
            except (json.JSONDecodeError, TypeError):
                result.append(item)
        return result

    @classmethod
    async def get_all_user_state(cls) -> dict[str, Any]:
        """获取完整的用户当前状态快照（用于 /state 接口）"""
        if _redis is None:
            raise RuntimeError("Context Graph 未连接")
        pattern = f"{_KEY_PREFIX}*"
        keys = await _redis.keys(pattern)
        if not keys:
            return {}
        values = await _redis.mget(*keys)
        prefix_len = len(_KEY_PREFIX)
        result = {}
        for key, val in zip(keys, values):
            short_key = key[prefix_len:]
            if val is not None:
                try:
                    result[short_key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    result[short_key] = val
        return result
