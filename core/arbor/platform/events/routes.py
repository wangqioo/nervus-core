from __future__ import annotations

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
    subject: str = Query(default=""),
):
    events = await request.app.state.event_service.get_recent(limit=limit, subject_prefix=subject)
    return {"count": len(events), "events": [e.model_dump(mode="json") for e in events]}
