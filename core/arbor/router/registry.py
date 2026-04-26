"""
App 注册表
维护所有已注册 App 的 manifest 和 endpoint，供路由引擎查询
"""

from __future__ import annotations
import json
import logging
from datetime import datetime

import asyncpg
import httpx

logger = logging.getLogger("nervus.arbor.registry")


class AppRegistry:
    def __init__(self):
        self._pool: asyncpg.Pool | None = None
        # 内存缓存：app_id -> {manifest, endpoint_url, status}
        self._cache: dict[str, dict] = {}

    async def init(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        await self._load_from_db()
        logger.info(f"App 注册表初始化，已加载 {len(self._cache)} 个 App")

    async def _load_from_db(self) -> None:
        if self._pool is None:
            return
        rows = await self._pool.fetch(
            "SELECT app_id, name, manifest, endpoint_url, status FROM app_registry WHERE status = 'online'"
        )
        for row in rows:
            self._cache[row["app_id"]] = {
                "manifest": json.loads(row["manifest"]),
                "endpoint_url": row["endpoint_url"],
                "status": row["status"],
                "name": row["name"],
            }

    async def register(self, manifest: dict, endpoint_url: str) -> None:
        """注册或更新一个 App"""
        app_id = manifest["id"]
        self._cache[app_id] = {
            "manifest": manifest,
            "endpoint_url": endpoint_url,
            "status": "online",
            "name": manifest.get("name", app_id),
        }

        if self._pool:
            await self._pool.execute("""
                INSERT INTO app_registry (app_id, name, version, description, manifest, endpoint_url, status, last_heartbeat)
                VALUES ($1, $2, $3, $4, $5, $6, 'online', NOW())
                ON CONFLICT (app_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    version = EXCLUDED.version,
                    manifest = EXCLUDED.manifest,
                    endpoint_url = EXCLUDED.endpoint_url,
                    status = 'online',
                    last_heartbeat = NOW()
            """,
                app_id,
                manifest.get("name", app_id),
                manifest.get("version", "1.0.0"),
                manifest.get("description", ""),
                json.dumps(manifest),
                endpoint_url,
            )
        logger.info(f"App 已注册: {app_id} @ {endpoint_url}")

    def get_app(self, app_id: str) -> dict | None:
        return self._cache.get(app_id)

    def get_all_apps(self) -> list[dict]:
        return list(self._cache.values())

    def find_subscribers(self, subject: str) -> list[dict]:
        """找到订阅了某事件主题的所有 App"""
        result = []
        for app_info in self._cache.values():
            manifest = app_info.get("manifest", {})
            for sub in manifest.get("subscribes", []):
                if self._subject_matches(subject, sub["subject"]):
                    result.append({
                        "app_id": manifest["id"],
                        "endpoint_url": app_info["endpoint_url"],
                        "handler": sub.get("handler", f"/intake/{subject.replace('.', '_')}"),
                        "filter": sub.get("filter", {}),
                        "subject_pattern": sub["subject"],
                    })
        return result

    def find_action_provider(self, app_id: str, action_name: str) -> dict | None:
        """找到提供某个 Action 的 App"""
        app = self._cache.get(app_id)
        if not app:
            return None
        for action in app["manifest"].get("actions", []):
            if action["name"] == action_name:
                return {
                    "app_id": app_id,
                    "endpoint_url": app["endpoint_url"],
                    "action": action,
                }
        return None

    @staticmethod
    def _subject_matches(subject: str, pattern: str) -> bool:
        """NATS 主题匹配（支持 * 和 > 通配符）"""
        if pattern == subject:
            return True
        if pattern.endswith(">"):
            prefix = pattern[:-1]
            return subject.startswith(prefix)
        parts_s = subject.split(".")
        parts_p = pattern.split(".")
        if len(parts_s) != len(parts_p):
            return False
        return all(p == "*" or p == s for p, s in zip(parts_p, parts_s))

    async def call_action(self, app_id: str, action_name: str, params: dict) -> dict:
        """调用指定 App 的 Action"""
        app = self._cache.get(app_id)
        if not app:
            raise ValueError(f"App {app_id} 未注册")

        url = f"{app['endpoint_url']}/action/{action_name}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=params)
            resp.raise_for_status()
            return resp.json()

    async def send_intake(self, app_id: str, handler: str, event: dict) -> dict:
        """向 App 的 /intake 接口发送事件"""
        app = self._cache.get(app_id)
        if not app:
            raise ValueError(f"App {app_id} 未注册")

        handler_path = handler.lstrip("/")
        url = f"{app['endpoint_url']}/{handler_path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=event)
            resp.raise_for_status()
            return resp.json()
