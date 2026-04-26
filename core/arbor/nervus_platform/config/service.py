from __future__ import annotations

import json
from pathlib import Path

from .schemas import PublicConfig


class ConfigService:
    def __init__(self, config_dir: str):
        self.config_dir = Path(config_dir)

    async def public_config(self) -> PublicConfig:
        path = self.config_dir / "public.json"
        if not path.exists():
            return PublicConfig()
        data = json.loads(path.read_text(encoding="utf-8"))
        return PublicConfig.model_validate(data)
