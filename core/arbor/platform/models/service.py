from __future__ import annotations

import logging
from typing import Any

import httpx

from .schemas import ChatRequest, ChatResponse, ModelInfo, ModelStatus

logger = logging.getLogger("nervus.platform.models")


class ModelService:
    def __init__(self, llm_url: str) -> None:
        self._llm_url = llm_url.rstrip("/")
        self._models: list[ModelInfo] = [
            ModelInfo(
                id="qwen3.5",
                name="Qwen 3.5 4B",
                provider="llama.cpp",
                context_length=4096,
            )
        ]

    def list_models(self) -> list[ModelInfo]:
        return self._models

    async def check_status(self) -> list[ModelInfo]:
        results: list[ModelInfo] = []
        async with httpx.AsyncClient(timeout=3.0) as client:
            for model in self._models:
                try:
                    resp = await client.get(f"{self._llm_url}/health")
                    if resp.status_code == 200 and resp.json().get("status") in ("ok", "online"):
                        results.append(model.model_copy(update={"status": ModelStatus.online}))
                    else:
                        results.append(model.model_copy(update={"status": ModelStatus.offline}))
                except Exception as exc:
                    logger.debug("model health check failed: %s", exc)
                    results.append(model.model_copy(update={"status": ModelStatus.offline}))
        return results

    async def chat(self, req: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": req.model,
            "messages": [m.model_dump() for m in req.messages],
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "stream": False,
        }
        payload.update(req.extra)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{self._llm_url}/v1/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            return ChatResponse(model=req.model, content="", error=f"upstream {exc.response.status_code}: {exc.response.text[:200]}")
        except Exception as exc:
            return ChatResponse(model=req.model, content="", error=str(exc))

        try:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
        except (KeyError, IndexError) as exc:
            return ChatResponse(model=req.model, content="", error=f"unexpected response shape: {exc}")

        return ChatResponse(model=req.model, content=content, usage=usage)
