from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from .schemas import PlatformEvent

logger = logging.getLogger("nervus.platform.events")


class EventService:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def init(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ingest(self, subject: str, payload: dict[str, Any], source_app: str = "system") -> PlatformEvent | None:
        if self._pool is None:
            logger.warning("EventService: no DB pool, skipping persist for %s", subject)
            return None
        row = await self._pool.fetchrow(
            """
            INSERT INTO platform_events (subject, payload, source_app)
            VALUES ($1, $2::jsonb, $3)
            RETURNING id::text, subject, payload, source_app, created_at
            """,
            subject,
            json.dumps(payload),
            source_app,
        )
        if row is None:
            return None
        payload_data = row["payload"]
        if isinstance(payload_data, str):
            payload_data = json.loads(payload_data)
        return PlatformEvent(
            id=row["id"],
            subject=row["subject"],
            payload=payload_data,
            source_app=row["source_app"],
            created_at=row["created_at"],
        )

    async def get_recent(self, limit: int = 50, subject_prefix: str = "") -> list[PlatformEvent]:
        if self._pool is None:
            return []
        if subject_prefix:
            rows = await self._pool.fetch(
                """
                SELECT id::text, subject, payload, source_app, created_at
                FROM platform_events
                WHERE subject LIKE $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                f"{subject_prefix}%",
                limit,
            )
        else:
            rows = await self._pool.fetch(
                """
                SELECT id::text, subject, payload, source_app, created_at
                FROM platform_events
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
        events = []
        for row in rows:
            payload_data = row["payload"]
            if isinstance(payload_data, str):
                payload_data = json.loads(payload_data)
            events.append(PlatformEvent(
                id=row["id"],
                subject=row["subject"],
                payload=payload_data,
                source_app=row["source_app"],
                created_at=row["created_at"],
            ))
        return events
