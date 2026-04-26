from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/public")
async def get_public_config(request: Request):
    config = await request.app.state.config_service.public_config()
    return config.model_dump()
