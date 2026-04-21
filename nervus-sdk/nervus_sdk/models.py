"""
Nervus SDK 核心数据模型
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Callable, Awaitable
from pydantic import BaseModel, Field


class Event(BaseModel):
    """Synapse Bus 标准化事件"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    subject: str                        # NATS 主题，如 media.photo.classified
    payload: dict[str, Any] = {}       # 事件数据
    source_app: str = ""               # 发布者 App ID
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: str | None = None  # 关联事件 ID（用于追踪跨 App 流程）


class SubscribeConfig(BaseModel):
    """事件订阅配置"""
    subject: str                        # NATS 主题（支持通配符 * 和 >）
    filter: dict[str, Any] = {}        # 过滤条件
    handler: str = ""                  # NSI /intake 路由路径


class ActionSpec(BaseModel):
    """App 能力声明"""
    name: str
    description: str = ""
    input: dict[str, str] = {}
    output: dict[str, str] = {}


class Manifest(BaseModel):
    """NSI App 能力声明（manifest.json）"""
    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    subscribes: list[SubscribeConfig] = []
    publishes: list[str] = []
    actions: list[ActionSpec] = []
    context_reads: list[str] = []
    context_writes: list[str] = []
    memory_writes: list[str] = []


class AppConfig(BaseModel):
    """App 运行时配置（从环境变量读取）"""
    app_id: str
    port: int = 8000
    nats_url: str = "nats://localhost:4222"
    redis_url: str = "redis://localhost:6379"
    postgres_url: str = "postgresql://nervus:nervus_secret@localhost:5432/nervus"
    llama_url: str = "http://localhost:8080"
    whisper_url: str = "http://localhost:8081"
    arbor_url: str = "http://localhost:8090"

    @classmethod
    def from_env(cls, app_id: str) -> "AppConfig":
        import os
        return cls(
            app_id=app_id,
            port=int(os.getenv("APP_PORT", "8000")),
            nats_url=os.getenv("NATS_URL", "nats://localhost:4222"),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            postgres_url=os.getenv("POSTGRES_URL", "postgresql://nervus:nervus_secret@localhost:5432/nervus"),
            llama_url=os.getenv("LLAMA_URL", "http://localhost:8080"),
            whisper_url=os.getenv("WHISPER_URL", "http://localhost:8081"),
            arbor_url=os.getenv("ARBOR_URL", "http://localhost:8090"),
        )


# 类型别名
EventHandler = Callable[[Event], Awaitable[Any]]
