from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ModelStatus(str, Enum):
    online = "online"
    offline = "offline"
    unknown = "unknown"


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str = "llama.cpp"
    context_length: int = 4096
    status: ModelStatus = ModelStatus.unknown


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "qwen3.5"
    messages: list[ChatMessage]
    max_tokens: int = 512
    temperature: float = 0.7
    stream: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    model: str
    content: str
    usage: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
