"""
NervusApp — SDK 主入口类
封装所有基础设施，提供 5 行接入体验
"""

from __future__ import annotations
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, Callable, Awaitable

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

from .models import Event, Manifest, AppConfig, EventHandler
from .bus import connect as bus_connect, disconnect as bus_disconnect, subscribe, emit as _emit, make_filter
from .context import connect as ctx_connect, disconnect as ctx_disconnect, Context
from .memory import connect as mem_connect, disconnect as mem_disconnect, MemoryGraph
from .llm import LLMClient

logger = logging.getLogger("nervus.app")


class NervusApp:
    """
    Nervus 生态 App 主类。

    示例：
        app = NervusApp("calorie-tracker")

        @app.on("media.photo.classified", filter={"tags_contains": ["food"]})
        async def handle_food(event):
            ...

        @app.action("analyze_meal")
        async def analyze_meal(photo_path: str) -> dict:
            ...

        app.run(port=8001)
    """

    def __init__(self, app_id: str):
        self.app_id = app_id
        self.config = AppConfig.from_env(app_id)

        # 基础设施客户端
        self.llm = LLMClient(self.config.llama_url)
        self.memory = MemoryGraph
        self.ctx = Context

        # 内部注册表
        self._handlers: list[tuple[str, dict, EventHandler]] = []   # (subject, filter, fn)
        self._actions: dict[str, Callable] = {}
        self._state_fn: Callable | None = None
        self._manifest: Manifest | None = None

        # FastAPI 实例
        self._api = FastAPI(title=f"Nervus App: {app_id}", version="1.0.0")
        self._setup_nsi_routes()

        logging.basicConfig(
            level=logging.INFO,
            format=f"%(asctime)s [{app_id}] %(levelname)s %(message)s"
        )

    # ── 装饰器 API ────────────────────────────────────────

    def on(self, subject: str, filter: dict = None):
        """订阅 Synapse Bus 事件的装饰器。

        @app.on("media.photo.classified", filter={"tags_contains": ["food"]})
        async def handle_food(event: Event):
            ...
        """
        def decorator(fn: EventHandler):
            self._handlers.append((subject, filter or {}, fn))
            return fn
        return decorator

    def action(self, name: str):
        """声明 App 能力的装饰器。

        @app.action("analyze_meal")
        async def analyze_meal(photo_path: str) -> dict:
            ...
        """
        def decorator(fn: Callable):
            self._actions[name] = fn
            return fn
        return decorator

    def state(self, fn: Callable):
        """暴露 App 当前状态的装饰器。

        @app.state
        async def get_state() -> dict:
            return {"today_calories": 1200}
        """
        self._state_fn = fn
        return fn

    # ── 手动 API ─────────────────────────────────────────

    async def emit(self, subject: str, payload: dict, correlation_id: str | None = None) -> None:
        """发布事件到 Synapse Bus"""
        await _emit(subject, payload, correlation_id)

    # ── NSI 标准接口 ──────────────────────────────────────

    def _setup_nsi_routes(self):
        api = self._api

        @api.get("/manifest")
        async def get_manifest():
            if self._manifest:
                return self._manifest.model_dump()
            return {"id": self.app_id, "name": self.app_id, "version": "1.0.0"}

        @api.get("/health")
        async def health():
            return {"status": "ok", "app_id": self.app_id}

        @api.post("/intake/{handler_name}")
        async def intake(handler_name: str, request: Request):
            """接收来自 Arbor 或其他 App 的数据"""
            body = await request.json()
            event = Event(**body) if "subject" in body else Event(
                subject=f"intake.{handler_name}",
                payload=body,
                source_app="arbor-core",
            )
            # 找到对应的 handler
            for subject, _filter, fn in self._handlers:
                if handler_name in subject.replace(".", "_") or f"intake/{handler_name}" in subject:
                    filter_fn = make_filter(_filter)
                    if filter_fn is None or filter_fn(event):
                        result = await fn(event)
                        return {"status": "ok", "result": result}
            raise HTTPException(status_code=404, detail=f"处理器 {handler_name} 未注册")

        @api.post("/action/{name}")
        async def call_action(name: str, request: Request):
            """执行具体能力"""
            if name not in self._actions:
                raise HTTPException(status_code=404, detail=f"Action {name} 未注册")
            body = await request.json()
            result = await self._actions[name](**body)
            return {"status": "ok", "result": result}

        @api.get("/query/{type}")
        async def query(type: str, request: Request):
            """回答关于自身数据的查询"""
            # 各 App 可以 override 此接口
            return {"status": "ok", "type": type, "data": []}

        @api.get("/state")
        async def get_state():
            """暴露当前状态快照"""
            if self._state_fn:
                state = await self._state_fn()
                return {"status": "ok", "state": state}
            return {"status": "ok", "state": {}}

    def mount(self, path: str, app_router):
        """挂载额外的 FastAPI 路由"""
        self._api.include_router(app_router, prefix=path)

    def set_manifest(self, manifest: Manifest):
        """设置 App 能力声明"""
        self._manifest = manifest

    # ── 生命周期 ──────────────────────────────────────────

    async def _startup(self):
        logger.info(f"[{self.app_id}] 正在启动...")

        # 连接基础设施
        await bus_connect(self.config.nats_url, self.app_id)
        await ctx_connect(self.config.redis_url)
        await mem_connect(self.config.postgres_url)

        # 注册事件订阅
        for subject, filter_config, handler in self._handlers:
            filter_fn = make_filter(filter_config)
            await subscribe(subject, handler, filter_fn=filter_fn, queue_group=self.app_id)

        # 向 Arbor Core 注册
        await self._register_with_arbor()

        logger.info(f"[{self.app_id}] 启动完成，监听端口 {self.config.port}")

    async def _shutdown(self):
        logger.info(f"[{self.app_id}] 正在关闭...")
        await bus_disconnect()
        await ctx_disconnect()
        await mem_disconnect()
        await self.llm.close()

    async def _register_with_arbor(self):
        """向 Arbor Core 注册 App"""
        try:
            manifest_data = self._manifest.model_dump() if self._manifest else {
                "id": self.app_id,
                "name": self.app_id,
                "version": "1.0.0",
            }
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{self.config.arbor_url}/apps/register",
                    json={
                        "manifest": manifest_data,
                        "endpoint_url": f"http://{self.app_id}:{self.config.port}",
                    }
                )
            logger.info(f"[{self.app_id}] 已向 Arbor Core 注册")
        except Exception as e:
            logger.warning(f"[{self.app_id}] 向 Arbor 注册失败（将在后台重试）: {e}")

    def run(self, port: int | None = None, host: str = "0.0.0.0"):
        """启动 App 服务"""
        if port:
            self.config.port = port

        @asynccontextmanager
        async def lifespan(api: FastAPI):
            await self._startup()
            yield
            await self._shutdown()

        self._api.router.lifespan_context = lifespan

        uvicorn.run(
            self._api,
            host=host,
            port=self.config.port,
            log_level="info",
            access_log=False,
        )
