from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request

from .schemas import EventIngestRequest

router = APIRouter()


@router.post("")
async def ingest_event(req: EventIngestRequest, request: Request):
    event = await request.app.state.event_service.ingest(req.subject, req.payload, req.source_app)
    if event is None:
        return {"status": "queued", "persisted": False}
    return {"status": "ok", "event": event.model_dump(mode="json")}


@router.get("/recent")
async def recent_events(
    request: Request,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    subject: str = Query(default="", description="subject 前缀过滤，如 health. 或 meeting."),
    source_app: str = Query(default="", description="来源 App 过滤"),
    since: Optional[datetime] = Query(default=None, description="起始时间（ISO 8601）"),
):
    svc = request.app.state.event_service
    events = await svc.get_recent(
        limit=limit,
        subject_prefix=subject,
        source_app=source_app,
        since=since,
        offset=offset,
    )
    return {"count": len(events), "events": [e.model_dump(mode="json") for e in events]}


@router.get("/count")
async def event_count(
    request: Request,
    subject: str = Query(default=""),
    source_app: str = Query(default=""),
):
    svc = request.app.state.event_service
    total = await svc.count(subject_prefix=subject, source_app=source_app)
    return {"total": total}
