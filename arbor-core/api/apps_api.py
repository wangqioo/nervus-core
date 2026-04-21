"""Arbor Core — App 管理 API"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class RegisterRequest(BaseModel):
    manifest: dict
    endpoint_url: str


@router.post("/register")
async def register_app(req: RegisterRequest):
    from main import registry
    await registry.register(req.manifest, req.endpoint_url)

    # 发布注册事件到总线
    import json
    from datetime import datetime
    from infra import nats_client
    event = {
        "subject": "system.app.registered",
        "payload": {"app_id": req.manifest["id"], "endpoint_url": req.endpoint_url},
        "source_app": "arbor-core",
        "timestamp": datetime.utcnow().isoformat(),
    }
    try:
        await nats_client.publish("system.app.registered", json.dumps(event).encode())
    except Exception:
        pass

    return {"status": "ok", "app_id": req.manifest["id"]}


@router.get("/list")
async def list_apps():
    from main import registry
    apps = registry.get_all_apps()
    return {
        "count": len(apps),
        "apps": [
            {
                "app_id": a["manifest"]["id"],
                "name": a["manifest"].get("name", ""),
                "version": a["manifest"].get("version", ""),
                "endpoint_url": a["endpoint_url"],
                "status": a["status"],
            }
            for a in apps
        ]
    }


@router.get("/{app_id}")
async def get_app(app_id: str):
    from main import registry
    app = registry.get_app(app_id)
    if not app:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"App {app_id} 未注册")
    return app
