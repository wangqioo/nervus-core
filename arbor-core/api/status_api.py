"""Arbor Core — 状态和健康检查 API"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    from infra import nats_client, redis_client, postgres_client
    return {
        "status": "ok",
        "services": {
            "nats": "connected" if nats_client.client else "disconnected",
            "redis": "connected" if redis_client.client else "disconnected",
            "postgres": "connected" if postgres_client.pool else "disconnected",
        }
    }


@router.get("/status")
async def system_status():
    """系统完整状态快照"""
    from main import registry, flow_loader
    from infra import redis_client
    import json

    # App 统计
    apps = registry.get_all_apps()

    # Context Graph 快照
    context = {}
    if redis_client.client:
        try:
            keys = await redis_client.client.keys("context:user:*")
            if keys:
                values = await redis_client.client.mget(*keys)
                for key, val in zip(keys, values):
                    short = key[len("context:user:"):]
                    if val:
                        try:
                            context[short] = json.loads(val)
                        except Exception:
                            context[short] = val
        except Exception:
            pass

    return {
        "arbor_core": "running",
        "apps_registered": len(apps),
        "flows_loaded": len(flow_loader.flows),
        "context_graph": context,
        "apps": [
            {"id": a["manifest"]["id"], "name": a["manifest"].get("name", ""), "status": a["status"]}
            for a in apps
        ],
    }


@router.get("/flows")
async def list_flows():
    """查看所有已加载的 Flow 配置"""
    from main import flow_loader
    return {
        "count": len(flow_loader.flows),
        "flows": [
            {
                "id": f["id"],
                "trigger": f.get("trigger"),
                "condition": f.get("condition", {}),
                "steps_count": len(f.get("steps", [])),
            }
            for f in flow_loader.flows.values()
        ]
    }


@router.get("/embedding/stats")
async def embedding_stats():
    """查看 Embedding Pipeline 队列状态"""
    from executor.embedding_pipeline import get_pipeline
    pipeline = get_pipeline()
    if pipeline:
        return pipeline.stats
    return {"queue_size": 0, "processed": 0, "failed": 0, "status": "not_initialized"}


@router.get("/logs")
async def get_execution_logs(limit: int = 20, status: str | None = None):
    """查看最近的执行日志"""
    from infra import postgres_client
    if postgres_client.pool is None:
        return {"logs": []}

    where = "WHERE status = $2" if status else ""
    params = [limit, status] if status else [limit]
    rows = await postgres_client.pool.fetch(
        f"SELECT flow_id, trigger_subject, routing_mode, status, duration_ms, created_at FROM execution_logs {where} ORDER BY created_at DESC LIMIT $1",
        *params
    )
    return {"logs": [dict(r) for r in rows]}
