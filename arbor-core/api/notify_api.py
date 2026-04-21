"""Arbor Core — 通知 API（全局弹窗）"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

router = APIRouter()


class GlobalPopupRequest(BaseModel):
    title: str
    body: str = ""
    source_app: str = ""
    metadata: dict[str, Any] = {}
    file_info: dict[str, Any] | None = None
    actions: list[dict] = []


@router.post("/global_popup")
async def trigger_global_popup(req: GlobalPopupRequest):
    """
    触发 Nervus 全局弹窗通知。
    Arbor Core 完成后台分析后主动推送，用户打开手机就看到系统已经处理完毕。
    """
    import json
    from infra import postgres_client

    if postgres_client.pool:
        await postgres_client.pool.execute(
            "INSERT INTO notifications (type, title, body, metadata) VALUES ($1, $2, $3, $4)",
            "global_popup",
            req.title,
            req.body,
            json.dumps({
                "source_app": req.source_app,
                "file_info": req.file_info,
                "actions": req.actions,
                **req.metadata,
            }),
        )

    return {"status": "ok", "message": "全局弹窗已触发"}


@router.get("/notifications")
async def get_notifications(unread_only: bool = True, limit: int = 20):
    """获取通知列表"""
    from infra import postgres_client
    if postgres_client.pool is None:
        return {"notifications": []}

    where = "WHERE is_read = FALSE" if unread_only else ""
    rows = await postgres_client.pool.fetch(
        f"SELECT id, type, title, body, metadata, is_read, created_at FROM notifications {where} ORDER BY created_at DESC LIMIT $1",
        limit
    )
    return {"notifications": [dict(r) for r in rows]}


@router.post("/notifications/{notification_id}/read")
async def mark_as_read(notification_id: str):
    from infra import postgres_client
    if postgres_client.pool:
        await postgres_client.pool.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = $1", notification_id
        )
    return {"status": "ok"}
