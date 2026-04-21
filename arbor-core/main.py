"""
Nervus Arbor Core — 神经路由中枢
端口：8090

职责：
  1. 订阅所有 Synapse Bus 事件
  2. 理解事件语义（快速/语义/动态三种模式）
  3. 路由到对应 App 并执行 Flow
  4. 管理 App 注册表
  5. 触发全局弹窗通知
"""

import asyncio
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from router.registry import AppRegistry
from router.fast_router import FastRouter
from router.semantic_router import SemanticRouter
from router.dynamic_router import DynamicRouter
from executor.flow_executor import FlowExecutor
from executor.flow_loader import FlowLoader
from executor.embedding_pipeline import init_pipeline, get_pipeline
from api import apps_api, notify_api, status_api
from infra import nats_client, redis_client, postgres_client
from infra.mdns import start_mdns, stop_mdns

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [arbor-core] %(levelname)s %(message)s"
)
logger = logging.getLogger("nervus.arbor")

# ── 全局单例 ──────────────────────────────────────────────

registry = AppRegistry()
flow_loader = FlowLoader(flows_dir=os.path.join(os.path.dirname(__file__), "flows"))
flow_executor = FlowExecutor(registry=registry)

fast_router = FastRouter(registry=registry, executor=flow_executor)
semantic_router = SemanticRouter(registry=registry, executor=flow_executor)
dynamic_router = DynamicRouter(registry=registry, executor=flow_executor)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Arbor Core 正在启动...")

    # 连接基础设施
    await nats_client.connect(os.getenv("NATS_URL", "nats://localhost:4222"))
    await redis_client.connect(os.getenv("REDIS_URL", "redis://localhost:6379"))
    await postgres_client.connect(os.getenv("POSTGRES_URL", "postgresql://nervus:nervus_secret@localhost:5432/nervus"))

    # 初始化各组件
    await registry.init(postgres_client.pool)
    flow_loader.load_all()
    fast_router.load_flows(flow_loader.flows)

    # 初始化 Embedding Pipeline
    llama_url = os.getenv("LLAMA_URL", "http://localhost:8080")
    pipeline = init_pipeline(llama_url, postgres_client.pool)
    await pipeline.start()

    # 订阅所有总线事件（通配符）
    asyncio.create_task(start_bus_listener())

    # 广播 mDNS 服务（_nervus._tcp），让 iOS 自动发现
    arbor_port = int(os.getenv("APP_PORT", "8090"))
    start_mdns(port=arbor_port)

    logger.info("Arbor Core 就绪")
    yield

    logger.info("Arbor Core 正在关闭...")
    stop_mdns()
    pipeline = get_pipeline()
    if pipeline:
        await pipeline.stop()
    await nats_client.disconnect()
    await redis_client.disconnect()
    await postgres_client.disconnect()


app = FastAPI(
    title="Nervus Arbor Core",
    description="神经路由中枢",
    version="1.0.0",
    lifespan=lifespan,
)

# 挂载 API 路由
app.include_router(apps_api.router, prefix="/apps", tags=["Apps"])
app.include_router(notify_api.router, prefix="/notify", tags=["Notify"])
app.include_router(status_api.router, prefix="", tags=["Status"])


async def start_bus_listener():
    """订阅 Synapse Bus 所有事件，分发给路由引擎"""
    nc = nats_client.client
    if nc is None:
        logger.error("NATS 未连接，无法启动总线监听")
        return

    async def on_event(msg):
        try:
            import json
            data = json.loads(msg.data.decode())
            subject = msg.subject
            await dispatch_event(subject, data)
        except Exception as e:
            logger.error(f"处理总线事件失败: {e}", exc_info=True)

    # 订阅所有域的事件
    subjects = [
        "media.>", "meeting.>", "health.>", "context.>",
        "memory.>", "knowledge.>", "system.>", "schedule.>",
    ]
    for subject in subjects:
        await nc.subscribe(subject, cb=on_event)
        logger.info(f"已订阅: {subject}")

    logger.info("总线监听已启动")


async def dispatch_event(subject: str, event_data: dict):
    """将事件分发给合适的路由引擎"""
    logger.debug(f"收到事件: {subject}")

    # 系统内部事件直接处理，不再路由
    if subject.startswith("system.app."):
        return

    # Step 1：快速路由（90% 场景，< 100ms）
    matched = await fast_router.route(subject, event_data)
    if matched:
        return

    # Step 2：语义路由（9% 场景，< 2s）
    matched = await semantic_router.route(subject, event_data)
    if matched:
        return

    # Step 3：动态规划（1% 场景，< 5s）
    await dynamic_router.route(subject, event_data)


if __name__ == "__main__":
    port = int(os.getenv("ARBOR_PORT", "8090"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info", access_log=False)
