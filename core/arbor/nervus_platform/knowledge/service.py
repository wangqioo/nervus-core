from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import asyncpg

from executor.embedding_pipeline import enqueue_knowledge_item
from .schemas import KnowledgeItem, KnowledgeSearchRequest, KnowledgeWriteRequest

if TYPE_CHECKING:
    from nervus_platform.models.service import ModelService

logger = logging.getLogger("nervus.platform.knowledge")


class KnowledgeService:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._model_service: ModelService | None = None

    async def init(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    def set_model_service(self, svc: ModelService) -> None:
        """注入 ModelService，用于向量语义搜索"""
        self._model_service = svc

    async def write(self, req: KnowledgeWriteRequest) -> KnowledgeItem | None:
        if self._pool is None:
            logger.warning("KnowledgeService: no DB pool")
            return None
        ts = req.timestamp or datetime.now(tz=timezone.utc)
        row = await self._pool.fetchrow(
            """
            INSERT INTO knowledge_items
                (type, title, content, summary, source_url, source_app, tags, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id::text, type, title, summary, source_url, source_app, tags, timestamp, created_at
            """,
            req.type,
            req.title,
            req.content,
            req.summary,
            req.source_url,
            req.source_app,
            req.tags,
            ts,
        )
        if row is None:
            return None
        item = _row_to_item(row)
        embed_text = f"{req.title} {req.summary} {req.content}"[:2000]
        enqueue_knowledge_item(item.id, embed_text)
        return item

    async def search(self, req: KnowledgeSearchRequest) -> list[KnowledgeItem]:
        if self._pool is None:
            return []

        # 向量语义搜索路径
        if req.semantic and self._model_service is not None:
            try:
                return await self._semantic_search(req)
            except Exception as exc:
                logger.warning("向量搜索失败，降级为关键词搜索: %s", exc)

        # 关键词搜索降级路径
        return await self._keyword_search(req)

    async def _semantic_search(self, req: KnowledgeSearchRequest) -> list[KnowledgeItem]:
        """使用 pgvector 余弦相似度搜索"""
        embedding = await self._model_service.embed(req.query)
        embedding_str = f"[{','.join(str(x) for x in embedding)}]"

        conditions = ["embedding IS NOT NULL"]
        params: list = [embedding_str]
        idx = 2

        if req.type:
            conditions.append(f"type = ${idx}")
            params.append(req.type)
            idx += 1

        if req.tags:
            conditions.append(f"tags && ${idx}::text[]")
            params.append(req.tags)
            idx += 1

        params.append(req.limit)
        where = " AND ".join(conditions)

        rows = await self._pool.fetch(
            f"""
            SELECT id::text, type, title, summary, source_url, source_app, tags, timestamp, created_at,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM knowledge_items
            WHERE {where}
            ORDER BY embedding <=> $1::vector
            LIMIT ${idx}
            """,
            *params,
        )
        return [_row_to_item(r) for r in rows]

    async def _keyword_search(self, req: KnowledgeSearchRequest) -> list[KnowledgeItem]:
        """关键词 ILIKE 文本搜索"""
        conditions = ["(title ILIKE $1 OR content ILIKE $1 OR summary ILIKE $1)"]
        params: list = [f"%{req.query}%"]
        idx = 2

        if req.type:
            conditions.append(f"type = ${idx}")
            params.append(req.type)
            idx += 1

        if req.tags:
            conditions.append(f"tags && ${idx}::text[]")
            params.append(req.tags)
            idx += 1

        params.append(req.limit)
        where = " AND ".join(conditions)
        rows = await self._pool.fetch(
            f"""
            SELECT id::text, type, title, summary, source_url, source_app, tags, timestamp, created_at
            FROM knowledge_items
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
        return [_row_to_item(r) for r in rows]


def _row_to_item(row: asyncpg.Record) -> KnowledgeItem:
    return KnowledgeItem(
        id=row["id"],
        type=row["type"],
        title=row["title"],
        summary=row["summary"] or "",
        source_url=row["source_url"] or "",
        source_app=row["source_app"],
        tags=list(row["tags"] or []),
        timestamp=row["timestamp"],
        created_at=row["created_at"],
    )
