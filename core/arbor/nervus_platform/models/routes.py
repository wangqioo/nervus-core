from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .schemas import ChatRequest

router = APIRouter()


@router.get("")
async def list_models(request: Request):
    svc = request.app.state.model_service
    models = svc.list_models()
    return {"count": len(models), "models": [m.model_dump() for m in models]}


@router.get("/defaults")
async def model_defaults(request: Request):
    svc = request.app.state.model_service
    return {"default_text": svc._default_text, "default_vision": svc._default_vision}


@router.put("/defaults")
async def set_defaults(body: dict, request: Request):
    svc = request.app.state.model_service
    svc.set_defaults(text=body.get("default_text"), vision=body.get("default_vision"))
    return {"default_text": svc._default_text, "default_vision": svc._default_vision}


@router.get("/status")
async def models_status(request: Request):
    models = await request.app.state.model_service.check_status()
    return {"models": [m.model_dump() for m in models]}


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    """标准阻塞式对话"""
    if req.stream:
        # 流式请求走 SSE
        svc = request.app.state.model_service
        return StreamingResponse(
            svc.chat_stream(req),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    result = await request.app.state.model_service.chat(req)
    if result.error:
        raise HTTPException(status_code=502, detail=result.error)
    return result.model_dump()


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """显式流式对话端点（等同于 chat 且 stream=true）"""
    svc = request.app.state.model_service
    return StreamingResponse(
        svc.chat_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class EmbedRequest(BaseModel):
    text: str


@router.post("/embed")
async def embed(body: EmbedRequest, request: Request):
    """文本向量嵌入（本地模型）"""
    svc = request.app.state.model_service
    try:
        embedding = await svc.embed(body.text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"embedding": embedding, "dim": len(embedding)}


class FallbackRequest(BaseModel):
    model_id: str


@router.put("/fallback")
async def set_fallback(body: FallbackRequest, request: Request):
    """设置本地模型失败时的云端 fallback 模型"""
    svc = request.app.state.model_service
    if body.model_id and body.model_id not in svc._configs:
        raise HTTPException(status_code=404, detail=f"model {body.model_id!r} not found")
    svc.set_fallback(body.model_id)
    return {"status": "ok", "fallback_model": svc._fallback_model}


class TestRequest(BaseModel):
    prompt: str = "你好"


@router.post("/{model_id}/test")
async def test_model(model_id: str, body: TestRequest, request: Request):
    svc = request.app.state.model_service
    if model_id not in svc._configs:
        raise HTTPException(status_code=404, detail=f"model {model_id!r} not found")
    result = await svc.test(model_id, body.prompt)
    if result.error:
        raise HTTPException(status_code=502, detail=result.error)
    return result.model_dump()


class KeyRequest(BaseModel):
    api_key: str


@router.put("/{model_id}/key")
async def set_api_key(model_id: str, body: KeyRequest, request: Request):
    svc = request.app.state.model_service
    ok = await svc.set_api_key(model_id, body.api_key)
    if not ok:
        raise HTTPException(status_code=404, detail=f"model {model_id!r} not found")
    return {"status": "ok", "model_id": model_id}
