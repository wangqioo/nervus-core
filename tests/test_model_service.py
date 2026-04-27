"""
ModelService 独立测试脚本
无需启动完整 Arbor，直接测试 ModelService 逻辑

用法（需要 llama.cpp 或真实云端 API Key）：

  # 测试本地模型
  LLAMA_URL=http://localhost:8080 python tests/test_model_service.py local

  # 测试云端模型（OpenAI compat）
  DEEPSEEK_API_KEY=sk-xxx python tests/test_model_service.py cloud deepseek-chat

  # 测试 Anthropic
  ANTHROPIC_API_KEY=sk-ant-xxx python tests/test_model_service.py anthropic claude-sonnet-4-6

  # 测试 fallback（模拟本地挂掉切云端）
  DEEPSEEK_API_KEY=sk-xxx python tests/test_model_service.py fallback deepseek-chat

  # 测试流式输出
  LLAMA_URL=http://localhost:8080 python tests/test_model_service.py stream

  # 查看所有模型状态
  python tests/test_model_service.py status
"""

from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

# 加入 core/arbor 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "core" / "arbor"))

MODELS_CONFIG = str(Path(__file__).parent.parent / "config" / "models.json")


def _make_model_service(llm_url: str):
    """构建 ModelService，注入空 Redis mock，不依赖真实 Redis"""
    # 在导入 service 之前 patch redis_client，避免连接真实 Redis
    with patch("infra.redis_client.get", new=AsyncMock(return_value=None)), \
         patch("infra.redis_client.set", new=AsyncMock(return_value=True)):
        from nervus_platform.models.service import ModelService
        svc = ModelService(llm_url, MODELS_CONFIG)
    return svc


async def _with_redis_mock(coro):
    """在 Redis mock 环境下运行协程"""
    with patch("infra.redis_client.get", new=AsyncMock(return_value=None)), \
         patch("infra.redis_client.set", new=AsyncMock(return_value=True)):
        return await coro


# ── 需要在 patch 上下文中重新导入，所以用工厂函数 ──────────

async def test_local(llm_url: str):
    print(f"\n[本地模型] llm_url={llm_url}")
    with patch("infra.redis_client.get", new=AsyncMock(return_value=None)):
        from nervus_platform.models.service import ModelService
        from nervus_platform.models.schemas import ChatRequest, ChatMessage
        svc = ModelService(llm_url, MODELS_CONFIG)
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="用一句话介绍你自己")],
            max_tokens=64,
            temperature=0.3,
        )
        result = await svc.chat(req)
    if result.error:
        print(f"  FAIL: {result.error}")
    else:
        print(f"  OK: {result.content[:100]}")
        print(f"  provider={result.provider}, model={result.model}")


async def test_cloud(llm_url: str, model_id: str):
    print(f"\n[云端模型] model_id={model_id}")
    # 从环境变量读取 API Key，模拟 Redis 里没有（走 env var 路径）
    with patch("infra.redis_client.get", new=AsyncMock(return_value=None)):
        from nervus_platform.models.service import ModelService
        from nervus_platform.models.schemas import ChatRequest, ChatMessage
        svc = ModelService(llm_url, MODELS_CONFIG)
        req = ChatRequest(
            model=model_id,
            messages=[ChatMessage(role="user", content="用一句话介绍你自己")],
            max_tokens=64,
            temperature=0.3,
        )
        result = await svc.chat(req)
    if result.error:
        print(f"  FAIL: {result.error}")
    else:
        print(f"  OK: {result.content[:100]}")
        print(f"  provider={result.provider}, model={result.model}")


async def test_anthropic(llm_url: str, model_id: str = "claude-sonnet-4-6"):
    print(f"\n[Anthropic] model_id={model_id}")
    with patch("infra.redis_client.get", new=AsyncMock(return_value=None)):
        from nervus_platform.models.service import ModelService
        from nervus_platform.models.schemas import ChatRequest, ChatMessage
        svc = ModelService(llm_url, MODELS_CONFIG)
        req = ChatRequest(
            model=model_id,
            messages=[
                ChatMessage(role="system", content="你是一个简洁的助手"),
                ChatMessage(role="user", content="用一句话介绍你自己"),
            ],
            max_tokens=64,
            temperature=0.3,
        )
        result = await svc.chat(req)
    if result.error:
        print(f"  FAIL: {result.error}")
    else:
        print(f"  OK: {result.content[:100]}")
        print(f"  provider={result.provider}, model={result.model}")


async def test_fallback(llm_url: str, fallback_model: str):
    print(f"\n[Fallback] 模拟本地失败 → fallback to {fallback_model}")
    with patch("infra.redis_client.get", new=AsyncMock(return_value=None)):
        from nervus_platform.models.service import ModelService
        from nervus_platform.models.schemas import ChatRequest, ChatMessage
        # 用一个不存在的本地 URL 触发 fallback
        svc = ModelService("http://127.0.0.1:19999", MODELS_CONFIG)
        svc._fallback_model = fallback_model
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="hello")],
            max_tokens=32,
        )
        result = await svc.chat(req)
    if result.error:
        print(f"  FAIL: {result.error}")
    else:
        print(f"  OK (fell back): {result.content[:100]}")
        print(f"  provider={result.provider}, model={result.model}")


async def test_status(llm_url: str):
    print(f"\n[模型状态] llm_url={llm_url}")
    with patch("infra.redis_client.get", new=AsyncMock(return_value=None)):
        from nervus_platform.models.service import ModelService
        svc = ModelService(llm_url, MODELS_CONFIG)
        models = await svc.check_status()
    for m in models:
        print(f"  {m.id:30s}  provider={m.provider:15s}  status={m.status}")


async def test_stream(llm_url: str):
    print(f"\n[流式输出] llm_url={llm_url}")
    with patch("infra.redis_client.get", new=AsyncMock(return_value=None)):
        from nervus_platform.models.service import ModelService
        from nervus_platform.models.schemas import ChatRequest, ChatMessage
        svc = ModelService(llm_url, MODELS_CONFIG)
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="数1到5，每个数字单独一行")],
            max_tokens=64,
            stream=True,
        )
        chunks = []
        async for chunk in svc.chat_stream(req):
            if chunk.strip() and chunk != "data: [DONE]\n\n":
                try:
                    data = json.loads(chunk.replace("data: ", ""))
                    content = data.get("content", "")
                    if content:
                        chunks.append(content)
                        print(f"  chunk: {content!r}")
                except Exception:
                    pass
    print(f"  合并: {''.join(chunks)[:80]}")


async def test_config():
    """不需要任何网络，只测试 models.json 加载是否正确"""
    print("\n[配置加载测试]")
    with patch("infra.redis_client.get", new=AsyncMock(return_value=None)):
        from nervus_platform.models.service import ModelService
        svc = ModelService("http://localhost:8080", MODELS_CONFIG)
    models = svc.list_models()
    print(f"  加载 {len(models)} 个模型:")
    for m in models:
        print(f"  {m.id:30s}  provider={m.provider}")
    print(f"  default_text={svc._default_text}")
    print(f"  default_vision={svc._default_vision}")
    print(f"  fallback_model={svc._fallback_model!r}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "config"
    llm_url = os.getenv("LLAMA_URL", "http://localhost:8080")

    if cmd == "config":
        asyncio.run(test_config())
    elif cmd == "local":
        asyncio.run(test_local(llm_url))
    elif cmd == "cloud":
        model_id = sys.argv[2] if len(sys.argv) > 2 else "deepseek-chat"
        asyncio.run(test_cloud(llm_url, model_id))
    elif cmd == "anthropic":
        model_id = sys.argv[2] if len(sys.argv) > 2 else "claude-sonnet-4-6"
        asyncio.run(test_anthropic(llm_url, model_id))
    elif cmd == "fallback":
        fallback = sys.argv[2] if len(sys.argv) > 2 else "deepseek-chat"
        asyncio.run(test_fallback(llm_url, fallback))
    elif cmd == "stream":
        asyncio.run(test_stream(llm_url))
    elif cmd == "status":
        asyncio.run(test_status(llm_url))
    else:
        print("用法: python tests/test_model_service.py [config|local|cloud|anthropic|fallback|stream|status]")
        print()
        print("  config     — 只测试 models.json 加载，无需网络")
        print("  local      — 测试本地 llama.cpp（需 LLAMA_URL）")
        print("  cloud      — 测试云端 OpenAI-compat（需对应 API Key 环境变量）")
        print("  anthropic  — 测试 Anthropic Claude（需 ANTHROPIC_API_KEY）")
        print("  fallback   — 测试本地挂掉切云端（需云端 API Key）")
        print("  stream     — 测试流式输出（需 llama.cpp）")
        print("  status     — 检测所有模型连通性")
