from __future__ import annotations

from pydantic import BaseModel, Field


class ExternalApp(BaseModel):
    id: str
    name: str
    url: str
    icon: str = "🌐"
    color: str = "linear-gradient(135deg,rgba(139,114,255,.25),rgba(107,82,240,.1))"
    description: str = ""


class PublicConfig(BaseModel):
    name: str = "Nervus"
    environment: str = "local"
    api_base: str = "/api"
    files_base: str = "/files/"
    external_apps: list[ExternalApp] = Field(default_factory=list)
