"""
LLM Client — 统一通过 Arbor ModelService 调用
所有 AI 请求（本地/云端）集中路由，不再直连 llama.cpp
"""

from __future__ import annotations
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("nervus.llm")


class LLMClient:
    """
    封装对 Arbor ModelService 的调用。
    所有请求统一走 Arbor /models/chat，由平台决定路由到本地还是云端。

    用法：
        client = LLMClient("http://arbor:8090")
        text = await client.chat("今天天气怎么样？")
        result = await client.vision("/path/to/image.jpg", "识别食物并估算热量")
    """

    def __init__(self, arbor_url: str, timeout: float = 180.0, model: str = ""):
        self.arbor_url = arbor_url.rstrip("/")
        self.timeout = timeout
        self.model = model  # 空字符串 = 使用平台默认模型
        self._client = httpx.AsyncClient(timeout=timeout)

    async def chat(
        self,
        prompt: str,
        system: str = "你是 Nervus 的 AI 助手，运行在边缘设备上，简洁准确地回答问题。",
        temperature: float = 0.3,
        max_tokens: int = 1024,
        json_mode: bool = False,
        model: str = "",
    ) -> str:
        """文字对话，返回模型回复文本"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        extra: dict[str, Any] = {}
        if json_mode:
            extra["response_format"] = {"type": "json_object"}

        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "extra": extra,
        }

        resp = await self._client.post(
            f"{self.arbor_url}/models/chat",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"]

    async def chat_json(
        self,
        prompt: str,
        system: str = "你是 Nervus 的 AI 助手。请以 JSON 格式返回结果。",
        temperature: float = 0.1,
        max_tokens: int = 1024,
        model: str = "",
    ) -> dict:
        """文字对话，返回解析后的 JSON 对象"""
        text = await self.chat(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            model=model,
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise ValueError(f"模型返回的不是有效 JSON: {text[:200]}")

    async def vision(
        self,
        image_path: str | Path,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 512,
        model: str = "",
    ) -> str:
        """
        视觉分析，返回模型对图片的描述/分析。
        image_path: 本地文件路径或 http(s) URL
        """
        image_content = _build_image_content(image_path)

        messages = [{
            "role": "user",
            "content": [
                image_content,
                {"type": "text", "text": prompt},
            ]
        }]

        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "vision": True,
        }

        resp = await self._client.post(
            f"{self.arbor_url}/models/chat",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"]

    async def vision_json(
        self,
        image_path: str | Path,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
        model: str = "",
    ) -> dict:
        """视觉分析，返回解析后的 JSON 对象"""
        json_prompt = f"{prompt}\n\n请以 JSON 格式返回结果。"
        text = await self.vision(image_path, json_prompt, temperature, max_tokens, model=model)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise ValueError(f"模型返回的不是有效 JSON: {text[:200]}")

    async def embed(self, text: str) -> list[float]:
        """生成文本向量嵌入（通过 Arbor 代理到本地模型）"""
        resp = await self._client.post(
            f"{self.arbor_url}/models/embed",
            json={"text": text},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]

    async def close(self) -> None:
        await self._client.aclose()


def _build_image_content(image_path: str | Path) -> dict:
    """将图片路径或 URL 转换为 OpenAI 多模态格式"""
    if str(image_path).startswith(("http://", "https://")):
        return {"type": "image_url", "image_url": {"url": str(image_path)}}

    path = Path(image_path)
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif",
    }
    mime = mime_map.get(path.suffix.lower(), "image/jpeg")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"}
    }
