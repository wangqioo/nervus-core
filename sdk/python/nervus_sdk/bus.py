"""
Synapse Bus — NATS JetStream 封装
提供简洁的 emit / subscribe 接口
"""

from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING

import nats
from nats.aio.client import Client as NATS
from nats.js import JetStreamContext

from .models import Event, EventHandler

if TYPE_CHECKING:
    from .app import NervusApp

logger = logging.getLogger("nervus.bus")

_nc: NATS | None = None
_js: JetStreamContext | None = None
_app_id: str = ""


async def connect(nats_url: str, app_id: str) -> None:
    global _nc, _js, _app_id
    _app_id = app_id
    _nc = await nats.connect(
        nats_url,
        name=f"nervus-{app_id}",
        reconnect_time_wait=2,
        max_reconnect_attempts=-1,      # 无限重连
        connect_timeout=5,
    )
    _js = _nc.jetstream()
    logger.info(f"[{app_id}] 已连接 NATS: {nats_url}")


async def disconnect() -> None:
    global _nc
    if _nc:
        await _nc.drain()
        _nc = None


async def emit(subject: str, payload: dict, correlation_id: str | None = None) -> None:
    """向 Synapse Bus 发布事件"""
    if _nc is None:
        raise RuntimeError("Bus 未连接，请先调用 connect()")

    event = Event(
        subject=subject,
        payload=payload,
        source_app=_app_id,
        correlation_id=correlation_id,
    )
    data = event.model_dump_json().encode()

    try:
        # 优先使用 JetStream 发布（持久化）
        if _js:
            await _js.publish(subject, data)
        else:
            await _nc.publish(subject, data)
        logger.debug(f"[{_app_id}] 发布事件: {subject}")
    except Exception as e:
        logger.error(f"[{_app_id}] 发布失败 {subject}: {e}")
        raise


async def subscribe(
    subject: str,
    handler: EventHandler,
    filter_fn=None,
    queue_group: str | None = None,
) -> None:
    """订阅 Synapse Bus 事件"""
    if _nc is None:
        raise RuntimeError("Bus 未连接，请先调用 connect()")

    async def _message_handler(msg):
        try:
            event = Event.model_validate_json(msg.data.decode())

            # 应用过滤器
            if filter_fn and not filter_fn(event):
                return

            await handler(event)

            # JetStream 消息需要手动 ack
            if hasattr(msg, "ack"):
                await msg.ack()

        except Exception as e:
            logger.error(f"[{_app_id}] 处理事件 {subject} 失败: {e}")
            if hasattr(msg, "nak"):
                await msg.nak()

    # 尝试 JetStream 持久化订阅
    if _js:
        try:
            consumer_name = f"{_app_id}-{subject.replace('.', '-').replace('*', 'wc').replace('>', 'all')}"
            await _js.subscribe(
                subject,
                cb=_message_handler,
                durable=consumer_name,
                queue=queue_group,
                manual_ack=True,
            )
            logger.info(f"[{_app_id}] JetStream 订阅: {subject}")
            return
        except Exception:
            pass  # 降级到普通订阅

    # 普通订阅（无持久化）
    await _nc.subscribe(subject, cb=_message_handler, queue=queue_group or "")
    logger.info(f"[{_app_id}] 普通订阅: {subject}")


def make_filter(conditions: dict):
    """
    构建事件过滤函数。

    支持的条件：
      tags_contains: ["food"]       payload.tags 包含任一值
      field_eq: {field: value}      payload.field == value
      field_contains: {field: val}  payload.field 包含 val
    """
    if not conditions:
        return None

    def _filter(event: Event) -> bool:
        payload = event.payload

        if "tags_contains" in conditions:
            tags = payload.get("tags", [])
            required = conditions["tags_contains"]
            if not any(t in tags for t in required):
                return False

        if "field_eq" in conditions:
            for field, value in conditions["field_eq"].items():
                if payload.get(field) != value:
                    return False

        if "field_contains" in conditions:
            for field, value in conditions["field_contains"].items():
                field_val = payload.get(field, "")
                if value not in str(field_val):
                    return False

        return True

    return _filter
