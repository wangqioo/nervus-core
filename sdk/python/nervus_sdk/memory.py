"""
Memory Graph — PostgreSQL + pgvector 封装
长期记忆存储与语义检索
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Any
import uuid

import asyncpg

logger = logging.getLogger("nervus.memory")

_pool: asyncpg.Pool | None = None


async def connect(postgres_url: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        postgres_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    logger.info(f"Memory Graph 已连接: {postgres_url}")


async def disconnect() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


class MemoryGraph:
    """
    Memory Graph 操作接口。

    用法：
        # 写入事件
        event_id = await MemoryGraph.write_event(
            type="meal",
            title="午餐 - 意大利面",
            timestamp=datetime.utcnow(),
            source_app="calorie-tracker",
            metadata={"calories": 680, "tags": ["food", "pasta"]},
            embedding=await app.llm.embed("意大利面 午餐 680kcal"),
        )

        # 语义检索
        results = await MemoryGraph.semantic_search("上次吃意大利面是什么时候", limit=5)
    """

    @staticmethod
    async def write_life_event(
        type: str,
        title: str,
        timestamp: datetime,
        source_app: str,
        description: str = "",
        metadata: dict = None,
        embedding: list[float] | None = None,
    ) -> str:
        """写入人生事件，返回事件 ID"""
        if _pool is None:
            raise RuntimeError("Memory Graph 未连接")

        import json
        event_id = str(uuid.uuid4())
        embedding_str = f"[{','.join(str(x) for x in embedding)}]" if embedding else None

        async with _pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO life_events (id, type, title, description, timestamp, source_app, metadata, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
            """,
                event_id, type, title, description, timestamp, source_app,
                json.dumps(metadata or {}), embedding_str
            )
        logger.debug(f"写入人生事件: {type} - {title}")
        return event_id

    @staticmethod
    async def write_knowledge_item(
        type: str,
        title: str,
        timestamp: datetime,
        source_app: str,
        content: str = "",
        summary: str = "",
        source_url: str = "",
        tags: list[str] = None,
        embedding: list[float] | None = None,
    ) -> str:
        """写入知识条目，返回条目 ID"""
        if _pool is None:
            raise RuntimeError("Memory Graph 未连接")

        item_id = str(uuid.uuid4())
        embedding_str = f"[{','.join(str(x) for x in embedding)}]" if embedding else None

        async with _pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO knowledge_items
                (id, type, title, content, summary, source_url, source_app, tags, timestamp, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::vector)
            """,
                item_id, type, title, content, summary, source_url, source_app,
                tags or [], timestamp, embedding_str
            )
        logger.debug(f"写入知识条目: {type} - {title}")
        return item_id

    @staticmethod
    async def semantic_search(
        query_embedding: list[float],
        table: str = "life_events",
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[dict]:
        """
        向量语义检索。
        query_embedding: 查询文本的向量表示
        table: "life_events" 或 "knowledge_items"
        """
        if _pool is None:
            raise RuntimeError("Memory Graph 未连接")

        embedding_str = f"[{','.join(str(x) for x in query_embedding)}]"
        type_clause = "AND type = $3" if type_filter else ""

        query = f"""
            SELECT id, type, title, description, timestamp, source_app, metadata,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM {table}
            WHERE embedding IS NOT NULL
            {type_clause}
            ORDER BY embedding <=> $1::vector
            LIMIT $2
        """

        async with _pool.acquire() as conn:
            if type_filter:
                rows = await conn.fetch(query, embedding_str, limit, type_filter)
            else:
                rows = await conn.fetch(query, embedding_str, limit)

        return [dict(row) for row in rows]

    @staticmethod
    async def add_relation(
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
        metadata: dict = None,
    ) -> None:
        """添加条目间的关系"""
        if _pool is None:
            raise RuntimeError("Memory Graph 未连接")

        import json
        async with _pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO item_relations (source_id, target_id, relation, weight, metadata)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (source_id, target_id, relation) DO UPDATE
                SET weight = EXCLUDED.weight, metadata = EXCLUDED.metadata
            """,
                source_id, target_id, relation, weight,
                json.dumps(metadata or {})
            )

    @staticmethod
    async def get_related(item_id: str, relation: str | None = None) -> list[dict]:
        """获取与某条目相关的所有条目"""
        if _pool is None:
            raise RuntimeError("Memory Graph 未连接")

        rel_clause = "AND relation = $2" if relation else ""
        query = f"""
            SELECT r.relation, r.weight,
                   COALESCE(le.title, ki.title) AS title,
                   COALESCE(le.type, ki.type) AS type,
                   r.target_id
            FROM item_relations r
            LEFT JOIN life_events le ON r.target_id = le.id
            LEFT JOIN knowledge_items ki ON r.target_id = ki.id
            WHERE r.source_id = $1
            {rel_clause}
            ORDER BY r.weight DESC
        """

        async with _pool.acquire() as conn:
            if relation:
                rows = await conn.fetch(query, item_id, relation)
            else:
                rows = await conn.fetch(query, item_id)

        return [dict(row) for row in rows]

    @staticmethod
    async def query_recent(
        source_app: str | None = None,
        type_filter: str | None = None,
        limit: int = 20,
        table: str = "life_events",
    ) -> list[dict]:
        """按时间倒序查询最近的记录"""
        if _pool is None:
            raise RuntimeError("Memory Graph 未连接")

        conditions = []
        params = []
        if source_app:
            params.append(source_app)
            conditions.append(f"source_app = ${len(params)}")
        if type_filter:
            params.append(type_filter)
            conditions.append(f"type = ${len(params)}")

        params.append(limit)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT id, type, title, description, timestamp, source_app, metadata, created_at
            FROM {table}
            {where}
            ORDER BY timestamp DESC
            LIMIT ${len(params)}
        """

        async with _pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [dict(row) for row in rows]
