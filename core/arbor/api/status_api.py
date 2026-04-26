from __future__ import annotations

from fastapi import APIRouter, Request

from infra import nats_client, redis_client, postgres_client

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "services": {
            "nats": "connected" if nats_client.client else "disconnected",
            "redis": "connected" if redis_client.client else "disconnected",
            "postgres": "connected" if postgres_client.pool else "disconnected",
        },
    }


@router.get("/status")
async def system_status(request: Request):
    registry = getattr(request.app.state, "app_registry", None)
    apps = registry.list_apps() if registry else []
    return {
        "platform": "nervus-core-platform",
        "version": "0.1.0",
        "apps_registered": len(apps),
        "apps": [
            {"id": app.id, "name": app.name, "status": app.status.value}
            for app in apps
        ],
    }


@router.get("/logs")
async def get_execution_logs(limit: int = 20):
    if postgres_client.pool is None:
        return {"logs": []}
    rows = await postgres_client.pool.fetch(
        "SELECT id, flow_id, trigger_subject, routing_mode, status, duration_ms, created_at "
        "FROM execution_logs ORDER BY created_at DESC LIMIT $1",
        limit,
    )
    return {
        "logs": [
            {
                "id": str(row["id"]),
                "flow_id": row["flow_id"],
                "trigger": row["trigger_subject"],
                "mode": row["routing_mode"],
                "status": row["status"],
                "duration_ms": row["duration_ms"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in rows
        ]
    }
