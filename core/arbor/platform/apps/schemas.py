from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AppType(str, Enum):
    nervus = "nervus"
    external = "external"


class AppStatus(str, Enum):
    online = "online"
    offline = "offline"
    degraded = "degraded"
    not_configured = "not_configured"
    disabled = "disabled"


class AppService(BaseModel):
    container: str = ""
    internal_url: str = ""
    port: int | None = None


class AppCapabilities(BaseModel):
    actions: list[dict[str, Any]] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)
    emits: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)


class AppManifest(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    id: str
    name: str
    type: AppType = AppType.nervus
    version: str = "0.1.0"
    description: str = ""
    icon: str = "🧩"
    route: str = ""
    service: AppService = Field(default_factory=AppService)
    capabilities: AppCapabilities = Field(default_factory=AppCapabilities)

    @classmethod
    def from_legacy(cls, data: dict[str, Any], endpoint_url: str = "") -> "AppManifest":
        actions = data.get("actions") or []
        consumes = []
        for item in data.get("subscribes") or []:
            if isinstance(item, str):
                consumes.append(item)
            elif isinstance(item, dict) and item.get("subject"):
                consumes.append(item["subject"])
        writes = []
        writes.extend(data.get("memory_writes") or [])
        writes.extend(data.get("context_writes") or [])
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            icon=data.get("icon", "🧩"),
            route=data.get("route", ""),
            service=AppService(internal_url=endpoint_url or data.get("endpoint_url", "")),
            capabilities=AppCapabilities(
                actions=actions,
                consumes=consumes,
                emits=data.get("publishes") or [],
                models=data.get("models") or [],
                writes=writes,
            ),
        )


class RegisterAppRequest(BaseModel):
    manifest: dict[str, Any]
    endpoint_url: str = ""


class RegisteredApp(BaseModel):
    id: str
    name: str
    type: AppType
    version: str
    description: str
    icon: str
    route: str
    status: AppStatus
    endpoint_url: str
    manifest: AppManifest


class AppStatusResponse(BaseModel):
    id: str
    status: AppStatus
    health: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
