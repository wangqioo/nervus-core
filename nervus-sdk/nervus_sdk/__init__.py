"""
nervus-sdk — Nervus 生态系统 Python SDK

用法示例：
    from nervus_sdk import NervusApp, Context, emit

    app = NervusApp("calorie-tracker")

    @app.on("media.photo.classified", filter={"tags_contains": ["food"]})
    async def handle_food_photo(event):
        result = await app.llm.vision(event.payload["photo_path"], "识别食物热量")
        await Context.set("physical.last_meal", event.timestamp)
        await emit("health.calorie.meal_logged", result)

    app.run(port=8001)
"""

from .app import NervusApp
from .context import Context
from .bus import emit, subscribe
from .models import Event, Manifest, AppConfig
from .llm import LLMClient
from .memory import MemoryGraph

__all__ = [
    "NervusApp",
    "Context",
    "emit",
    "subscribe",
    "Event",
    "Manifest",
    "AppConfig",
    "LLMClient",
    "MemoryGraph",
]

__version__ = "1.0.0"
