import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk.llm import LLMClient

logger = logging.getLogger("file-manager.analyzer")

from models.file import FileSummary, FileType, FileStatus
from services.storage import get_file_absolute_path, save_meta
from services.url_classifier import (
    classify_url, fetch_bilibili_summary, fetch_wechat_summary,
    fetch_generic_summary, fetch_linkbox,
)
from utils.config import LLAMA_URL, GLM_API_KEY, GLM_MODEL, GLM_VISION_MODEL

_llm = LLMClient(LLAMA_URL, timeout=60.0)


def _extract_json(text: str) -> dict:
    if not text:
        return {}
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def _glm_chat_sync(prompt: str, system: str) -> str:
    from zhipuai import ZhipuAI
    client = ZhipuAI(api_key=GLM_API_KEY)
    r = client.chat.completions.create(
        model=GLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    )
    return r.choices[0].message.content


def _glm_vision_sync(image_path: Path, prompt: str) -> str:
    import base64
    from zhipuai import ZhipuAI
    suffix = image_path.suffix.lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}.get(suffix.lstrip("."), "image/jpeg")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    client = ZhipuAI(api_key=GLM_API_KEY)
    r = client.chat.completions.create(
        model=GLM_VISION_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
    )
    return r.choices[0].message.content


async def _chat(prompt: str, system: str = "你是一个内容分析助手，只输出JSON，不要其他内容。") -> str:
    if GLM_API_KEY:
        # ZhipuAI SDK 是同步的，必须在线程池中运行避免阻塞事件循环
        return await asyncio.to_thread(_glm_chat_sync, prompt, system)
    return await _llm.chat(prompt, system=system, temperature=0.3, max_tokens=512)


async def _vision(image_path: Path, prompt: str) -> str:
    if GLM_API_KEY:
        return await asyncio.to_thread(_glm_vision_sync, image_path, prompt)
    return await _llm.vision(image_path, prompt, temperature=0.2, max_tokens=512)


def _extract_text_from_file(file_path: Path, file_type: FileType) -> str:
    text = ""
    try:
        if file_type == FileType.document:
            suffix = file_path.suffix.lower()
            if suffix == ".pdf":
                text = _extract_pdf(file_path)
            elif suffix in (".docx", ".doc"):
                text = _extract_docx(file_path)
            elif suffix in (".txt", ".md", ".csv"):
                text = file_path.read_text(encoding="utf-8", errors="ignore")[:3000]
    except Exception as e:
        text = f"文件读取失败: {e}"
    return text[:3000]


def _extract_pdf(file_path: Path) -> str:
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(file_path))
    except ImportError:
        pass
    try:
        import pypdf
        reader = pypdf.PdfReader(str(file_path))
        return "\n".join(p.extract_text() or "" for p in reader.pages[:10])
    except ImportError:
        pass
    return "PDF文本提取需要安装 pdfminer.six 或 pypdf"


def _extract_docx(file_path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(file_path))
        return "\n".join(p.text for p in doc.paragraphs)
    except ImportError:
        return "Word文档提取需要安装 python-docx"


async def analyze_file(meta: FileSummary) -> FileSummary:
    try:
        if meta.type == FileType.link:
            result = await _analyze_link(meta.url)
        elif meta.type == FileType.image:
            result = await _analyze_image(meta)
        elif meta.type == FileType.document:
            result = await _analyze_document(meta)
        elif meta.type == FileType.video:
            result = _analyze_video(meta)
        elif meta.type == FileType.audio:
            result = _analyze_audio(meta)
        else:
            result = await _analyze_other(meta)

        meta.summary = result.get("summary", "")
        meta.description = result.get("description", "")
        meta.keywords = result.get("keywords", [])
        meta.highlights = result.get("highlights", [])
        meta.og_image = result.get("og_image")
        meta.favicon_url = result.get("favicon_url")
        meta.status = FileStatus.ready
        meta.analyzed_at = datetime.now()
    except Exception as e:
        logger.error("analyze_file [%s] failed: %s", meta.id, e, exc_info=True)
        meta.status = FileStatus.failed
        meta.error = str(e)

    save_meta(meta)

    from services.events import emit as _emit
    await _emit(meta.model_dump(mode="json"))
    return meta


async def _analyze_image(meta: FileSummary) -> dict:
    file_path = get_file_absolute_path(meta)
    if not file_path or not file_path.exists():
        return {"summary": f"图片：{meta.original_filename}", "description": "", "keywords": ["图片"], "highlights": []}

    prompt = (
        "请分析这张图片，生成JSON格式简介：\n"
        '{"summary":"一句话描述（20字内）","description":"详细描述（100字内）","keywords":["关键词1","关键词2","关键词3"]}\n'
        "只输出JSON，不要其他内容。"
    )
    try:
        raw = await _vision(file_path, prompt)
        result = _extract_json(raw)
        if result:
            return result
    except Exception:
        pass
    return {"summary": f"图片：{meta.original_filename}", "description": "", "keywords": ["图片"], "highlights": []}


async def _analyze_document(meta: FileSummary) -> dict:
    file_path = get_file_absolute_path(meta)
    text = _extract_text_from_file(file_path, meta.type) if file_path else ""
    if not text:
        text = f"文件名：{meta.original_filename}"

    prompt = (
        f"请分析以下文档内容，生成JSON格式简介：\n\n{text}\n\n"
        '{"summary":"一句话描述文档主题（20字内）","description":"文档核心内容概述（100字内）",'
        '"keywords":["关键词1","关键词2","关键词3"],"highlights":["亮点1","亮点2"]}\n只输出JSON。'
    )
    try:
        raw = await _chat(prompt, system="你是一个文档分析助手，专注于提取核心信息并生成结构化简介。只输出JSON。")
        result = _extract_json(raw)
        if result:
            return result
    except Exception:
        pass
    return {"summary": f"文档：{meta.original_filename}", "description": text[:100], "keywords": ["文档"], "highlights": []}


def _analyze_video(meta: FileSummary) -> dict:
    return {
        "summary": f"视频：{meta.original_filename}",
        "description": f"视频大小：{(meta.file_size or 0) // 1024 // 1024:.1f}MB",
        "keywords": ["视频"],
        "highlights": [],
    }


def _analyze_audio(meta: FileSummary) -> dict:
    return {
        "summary": f"音频：{meta.original_filename}",
        "description": f"音频文件，大小：{(meta.file_size or 0) // 1024:.0f}KB",
        "keywords": ["音频"],
        "highlights": [],
    }


async def _analyze_other(meta: FileSummary) -> dict:
    prompt = (
        f"根据文件名生成简介，文件名：{meta.original_filename}\n"
        '{"summary":"一句话简介","description":"描述","keywords":["词1"],"highlights":[]}\n只输出JSON。'
    )
    try:
        raw = await _chat(prompt)
        result = _extract_json(raw)
        if result:
            return result
    except Exception:
        pass
    return {"summary": meta.original_filename, "description": "", "keywords": [], "highlights": []}


async def _analyze_link(url: str) -> dict:
    # 1. 尝试 LinkBox API（最优）
    linkbox_result = await fetch_linkbox(url)
    if linkbox_result:
        base = linkbox_result
    else:
        # 2. 按 URL 类型分别抓取
        link_type = classify_url(url)
        if link_type == "wechat":
            base = await fetch_wechat_summary(url)
        elif link_type == "bilibili":
            base = await fetch_bilibili_summary(url)
        else:
            base = await fetch_generic_summary(url)

    # 3. 用 LLM 增强摘要（如果有正文内容）
    content = base.pop("_content", "")
    if content and len(content) > 100:
        try:
            prompt = (
                f"为以下内容生成简介JSON：\n标题：{base.get('summary','')}\n正文节选：{content[:1500]}\n\n"
                '{"summary":"一句话核心（20字内）","description":"摘要（100字内）",'
                '"keywords":["词1","词2","词3"],"highlights":["亮点1","亮点2"]}\n只输出JSON。'
            )
            enhanced = _extract_json(await _chat(prompt))
            if enhanced:
                base.update({k: v for k, v in enhanced.items() if v})
        except Exception:
            pass

    return base


async def search_files(query: str, files: list[FileSummary]) -> list[dict]:
    if not files:
        return []

    ready_files = [f for f in files if f.status == FileStatus.ready]
    if not ready_files:
        return []

    file_list_text = "\n".join(
        f"- ID:{f.id} 文件名:{f.original_filename} 类型:{f.type.value} 简介:{f.summary or '无'} 关键词:{','.join(f.keywords)}"
        for f in ready_files
    )

    prompt = (
        f"文件列表：\n{file_list_text}\n\n"
        f"搜索词：{query}\n\n"
        "规则：\n"
        "1. 只返回摘要/关键词中有直接证据的文件\n"
        "2. match_score 代表确信度（0~1），低于 0.6 的不要返回\n"
        "3. match_reason 引用文件摘要/关键词中的具体内容\n"
        "4. 最多返回5个，没有匹配则 results 为空数组\n\n"
        '返回JSON（只输出JSON）：\n{"results":[{"id":"文件id","match_score":0.85,"match_reason":"摘要中提到..."}]}'
    )
    system = (
        "你是一个严格的文件搜索助手。"
        "只返回与搜索词有明确直接关联的文件——文件的摘要或关键词中必须有清晰证据。"
        "宁可少返回，不可滥返回。只输出JSON。"
    )

    try:
        raw = await _chat(prompt, system=system)
        data = _extract_json(raw)
        results = data.get("results", [])

        def _score(r):
            try:
                return float(r.get("match_score") or 0)
            except (TypeError, ValueError):
                return 0.0

        return [r for r in results if _score(r) >= 0.6]
    except Exception:
        return []
