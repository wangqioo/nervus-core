from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeWriteRequest(BaseModel):
    type: str
    title: str
    content: str = ""
    summary: str = ""
    source_url: str = ""
    source_app: str
    tags: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None


class KnowledgeSearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, le=50)
    type: str | None = None
    tags: list[str] = Field(default_factory=list)


class KnowledgeItem(BaseModel):
    id: str
    type: str
    title: str
    summary: str
    source_url: str
    source_app: str
    tags: list[str]
    timestamp: datetime
    created_at: datetime
