"""
SDK LLMClient 独立测试脚本
验证 SDK 通过 Arbor 代理调用 AI 的行为

用法（需要 Arbor 已启动）：

  # 测试文字对话
  ARBOR_URL=http://localhost:8090 python tests/test_sdk_llm.py chat

  # 测试视觉分析
  ARBOR_URL=http://localhost:8090 python tests/test_sdk_llm.py vision /path/to/image.jpg

  # 测试 JSON 模式
  ARBOR_URL=http://localhost:8090 python tests/test_sdk_llm.py json

  # 测试向量嵌入
  ARBOR_URL=http://localhost:8090 python tests/test_sdk_llm.py embed
"""

from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "sdk" / "python"))

from nervus_sdk.llm import LLMClient


async def test_chat(arbor_url: str):
    print(f"\n[SDK chat] arbor_url={arbor_url}")
    client = LLMClient(arbor_url)
    try:
        result = await client.chat("用一句话介绍 Nervus 系统")
        print(f"  OK: {result[:120]}")
    except Exception as e:
        print(f"  FAIL: {e}")
    finally:
        await client.close()


async def test_json(arbor_url: str):
    print(f"\n[SDK chat_json] arbor_url={arbor_url}")
    client = LLMClient(arbor_url)
    try:
        result = await client.chat_json(
            "返回一个包含 name 和 version 字段的 JSON，描述 Nervus 系统"
        )
        print(f"  OK: {result}")
    except Exception as e:
        print(f"  FAIL: {e}")
    finally:
        await client.close()


async def test_embed(arbor_url: str):
    print(f"\n[SDK embed] arbor_url={arbor_url}")
    client = LLMClient(arbor_url)
    try:
        embedding = await client.embed("Nervus 个人 AI 操作系统")
        print(f"  OK: dim={len(embedding)}, first5={embedding[:5]}")
    except Exception as e:
        print(f"  FAIL: {e}")
    finally:
        await client.close()


async def test_vision(arbor_url: str, image_path: str):
    print(f"\n[SDK vision] image={image_path}")
    client = LLMClient(arbor_url)
    try:
        result = await client.vision(image_path, "描述这张图片的内容")
        print(f"  OK: {result[:120]}")
    except Exception as e:
        print(f"  FAIL: {e}")
    finally:
        await client.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "chat"
    arbor_url = os.getenv("ARBOR_URL", "http://localhost:8090")

    if cmd == "chat":
        asyncio.run(test_chat(arbor_url))
    elif cmd == "json":
        asyncio.run(test_json(arbor_url))
    elif cmd == "embed":
        asyncio.run(test_embed(arbor_url))
    elif cmd == "vision":
        img = sys.argv[2] if len(sys.argv) > 2 else ""
        if not img:
            print("用法: python tests/test_sdk_llm.py vision /path/to/image.jpg")
            sys.exit(1)
        asyncio.run(test_vision(arbor_url, img))
    else:
        print("用法: python tests/test_sdk_llm.py [chat|json|embed|vision]")
