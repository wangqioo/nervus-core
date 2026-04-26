from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventIngestRequest(BaseModel):
    subject: str
    payload: dict[str, Any] = Field(default_factory=dict)
    source_app: str = "system"


class PlatformEvent(BaseModel):
    id: str
    subject: str
    payload: dict[str, Any]
    source_app: str
    created_at: datetime
