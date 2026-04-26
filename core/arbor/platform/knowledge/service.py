from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg

from executor.embedding_pipeline import enqueue_knowledge_item
from .schemas import KnowledgeItem, KnowledgeSearchRequest, KnowledgeWriteRequest

logger = logging.getLogger("nervus.platform.knowledge")


class KnowledgeService:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def init(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

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
