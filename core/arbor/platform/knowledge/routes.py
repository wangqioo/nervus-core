from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .schemas import KnowledgeSearchRequest, KnowledgeWriteRequest

router = APIRouter()


@router.post("")
async def write_knowledge(req: KnowledgeWriteRequest, request: Request):
    item = await request.app.state.knowledge_service.write(req)
    if item is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return {"status": "ok", "item": item.model_dump(mode="json")}


@router.post("/search")
async def search_knowledge(req: KnowledgeSearchRequest, request: Request):
    items = await request.app.state.knowledge_service.search(req)
    return {"count": len(items), "items": [i.model_dump(mode="json") for i in items]}
