"""
Flow 加载器 — 从 JSON 文件加载和热更新流程配置
"""

from __future__ import annotations
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("nervus.arbor.flow_loader")


class FlowLoader:
    def __init__(self, flows_dir: str):
        self.flows_dir = Path(flows_dir)
        self.flows: dict[str, dict] = {}  # flow_id -> flow_config

    def load_all(self) -> None:
        """加载 flows/ 目录下所有 JSON 文件"""
        if not self.flows_dir.exists():
            logger.warning(f"flows 目录不存在: {self.flows_dir}")
            return

        count = 0
        for path in self.flows_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    flow = json.load(f)
                if isinstance(flow, list):
                    for f in flow:
                        self.flows[f["id"]] = f
                        count += 1
                else:
                    self.flows[flow["id"]] = flow
                    count += 1
            except Exception as e:
                logger.error(f"加载 flow 失败 {path}: {e}")

        logger.info(f"加载 {count} 个 Flow 配置")

    def get_flows_for_subject(self, subject: str) -> list[dict]:
        """返回所有触发条件匹配的 Flow"""
        result = []
        for flow in self.flows.values():
            if self._trigger_matches(flow.get("trigger", ""), subject):
                result.append(flow)
        return result

    @staticmethod
    def _trigger_matches(trigger: str, subject: str) -> bool:
        if trigger == subject:
            return True
        if trigger.endswith(">"):
            return subject.startswith(trigger[:-1])
        parts_t = trigger.split(".")
        parts_s = subject.split(".")
        if len(parts_t) != len(parts_s):
            return False
        return all(t == "*" or t == s for t, s in zip(parts_t, parts_s))
