from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from infra import nats_client, postgres_client, redis_client
from infra.mdns import start_mdns, stop_mdns
from infra.settings import Settings
from platform.apps.registry import AppRegistry
from platform.apps.routes import router as apps_router
from platform.config.routes import router as config_router
from platform.config.service import ConfigService
from platform.models.service import ModelService
from platform.models.routes import router as models_router
from platform.events.service import EventService
from platform.events.routes import router as events_router
from platform.knowledge.service import KnowledgeService
from platform.knowledge.routes import router as knowledge_router
from api import notify_api, status_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [arbor-core] %(levelname)s %(message)s",
)
logger = logging.getLogger("nervus.arbor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Arbor Core Platform v0.1 starting...")
    settings = Settings.from_env()
    app.state.settings = settings

    await nats_client.connect(settings.nats_url)
    await redis_client.connect(settings.redis_url)
    await postgres_client.connect(settings.postgres_url)

    app.state.config_service = ConfigService(settings.config_dir)

    app.state.app_registry = AppRegistry()
    await app.state.app_registry.init(postgres_client.pool)

    app.state.model_service = ModelService(settings.llm_url)

    app.state.event_service = EventService()
    await app.state.event_service.init(postgres_client.pool)

    app.state.knowledge_service = KnowledgeService()
    await app.state.knowledge_service.init(postgres_client.pool)

    asyncio.create_task(start_bus_listener())
    start_mdns(port=settings.app_port)

    logger.info("Arbor Core Platform v0.1 ready")
    yield

    logger.info("Arbor Core Platform v0.1 shutting down...")
    stop_mdns()
    await nats_client.disconnect()
    await redis_client.disconnect()
    await postgres_client.disconnect()


app = FastAPI(
    title="Nervus Arbor Core Platform",
    description="Nervus platform core services",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(config_router, prefix="/config", tags=["Config"])
app.include_router(apps_router, prefix="/apps", tags=["Apps"])
app.include_router(models_router, prefix="/models", tags=["Models"])
app.include_router(events_router, prefix="/events", tags=["Events"])
app.include_router(knowledge_router, prefix="/platform/knowledge", tags=["Knowledge"])
app.include_router(notify_api.router, prefix="/notify", tags=["Notify"])
app.include_router(status_api.router, prefix="", tags=["Status"])


async def start_bus_listener():
    nc = nats_client.client
    if nc is None:
        logger.error("NATS is not connected; bus listener not started")
        return

    event_service: EventService = app.state.event_service

    async def on_event(msg):
        try:
            data = json.loads(msg.data.decode())
            logger.debug("received bus event %s: %s", msg.subject, data)
            await event_service.ingest(
                subject=msg.subject,
                payload=data,
                source_app=data.get("source_app", "bus"),
            )
        except Exception:
            logger.exception("failed to process bus event")

    for subject in ["media.>", "meeting.>", "health.>", "context.>", "memory.>", "knowledge.>", "system.>", "schedule.>"]:
        await nc.subscribe(subject, cb=on_event)
        logger.info("subscribed to %s", subject)


if __name__ == "__main__":
    port = int(os.getenv("ARBOR_PORT", os.getenv("APP_PORT", "8090")))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info", access_log=False)
