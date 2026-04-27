"""
动态规划引擎 — 多事件关联，自主生成执行计划，< 5s
约 1% 场景
"""

from __future__ import annotations
import json
import logging
import time
from collections import deque

from nervus_platform.apps.registry import AppRegistry
from nervus_platform.models.service import ModelService
from nervus_platform.models.schemas import ChatRequest, ChatMessage
from executor.flow_executor import FlowExecutor

logger = logging.getLogger("nervus.arbor.dynamic_router")

# 事件时间窗口（秒），窗口内相似事件可能需要联动
CORRELATION_WINDOW = 300  # 5 分钟

PLANNING_PROMPT = """你是 Nervus 神经路由系统的动态规划引擎。
你检测到多个在时间上关联的事件，需要制定一个执行计划。

关联事件列表：
{events}

已注册的 App 和能力：
{apps}

用户当前状态：
{context}

请分析这些事件之间的语义关联，判断是否需要联合处理。
如果需要，请生成一个执行计划。

以 JSON 格式返回：
{{
  "correlation_detected": true/false,
  "correlation_type": "关联类型描述",
  "plan": [
    {{
      "step": 1,
      "app_id": "目标App",
      "action": "action名称（可选）",
      "params": {{}},
      "description": "这步做什么"
    }}
  ],
  "reasoning": "为什么这样规划"
}}"""


class DynamicRouter:
    def __init__(self, registry: AppRegistry, executor: FlowExecutor,
                 model_service: ModelService | None = None):
        self.registry = registry
        self.executor = executor
        self._recent_events: deque = deque(maxlen=50)
        self._model_service = model_service

    def set_model_service(self, svc: ModelService) -> None:
        self._model_service = svc

    async def route(self, subject: str, event_data: dict) -> bool:
        """
        动态规划路由：检测多事件关联，自主生成计划。
        """
        now = time.time()
        self._recent_events.append({
            "subject": subject,
            "payload": event_data.get("payload", {}),
            "timestamp": now,
        })

        correlated = self._find_correlated(subject, now)
        if len(correlated) < 2:
            return False

        if not self._has_semantic_signal(subject, correlated):
            return False

        logger.info("检测到 %d 个关联事件，启动动态规划", len(correlated))

        plan = await self._generate_plan(correlated)
        if not plan or not plan.get("correlation_detected"):
            return False

        logger.info("动态规划: %s — %s",
                    plan.get("correlation_type"), plan.get("reasoning", "")[:80])

        await self._execute_plan(plan, event_data)
        return True

    def _find_correlated(self, current_subject: str, now: float) -> list[dict]:
        cutoff = now - CORRELATION_WINDOW
        recent = [e for e in self._recent_events if e["timestamp"] >= cutoff]
        current_domain = current_subject.split(".")[0]
        return [e for e in recent
                if e["subject"].split(".")[0] == current_domain
                or self._semantically_related(current_subject, e["subject"])]

    def _semantically_related(self, s1: str, s2: str) -> bool:
        related_pairs = [
            ("meeting.recording.processed", "media.photo.classified"),
            ("media.photo.classified", "memory.travel.moment_captured"),
            ("health.calorie.meal_logged", "context.user_state.updated"),
        ]
        for a, b in related_pairs:
            if (s1.startswith(a.split(".")[0]) and s2.startswith(b.split(".")[0])) or \
               (s2.startswith(a.split(".")[0]) and s1.startswith(b.split(".")[0])):
                return True
        return False

    def _has_semantic_signal(self, subject: str, events: list[dict]) -> bool:
        subjects = {e["subject"] for e in events}
        signal_groups = [
            {"meeting.recording.processed", "media.photo.classified"},
        ]
        for group in signal_groups:
            if group.issubset(subjects):
                return True
        return False

    async def _generate_plan(self, events: list[dict]) -> dict:
        if self._model_service is None:
            logger.warning("DynamicRouter: ModelService 未设置，跳过动态规划")
            return {}

        context = await self._get_context()
        apps_summary = self._get_apps_summary()

        events_text = json.dumps(
            [{"subject": e["subject"], "payload": e["payload"]} for e in events],
            ensure_ascii=False, indent=2
        )

        prompt = PLANNING_PROMPT.format(
            events=events_text,
            apps=apps_summary,
            context=json.dumps(context, ensure_ascii=False),
        )

        req = ChatRequest(
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=0.1,
            max_tokens=1024,
            extra={"response_format": {"type": "json_object"}},
        )

        try:
            result = await self._model_service.chat(req)
            if result.error:
                logger.error("动态规划生成失败: %s", result.error)
                return {}
            return json.loads(result.content)
        except Exception as e:
            logger.error("动态规划生成失败: %s", e)
            return {}

    async def _execute_plan(self, plan: dict, trigger_event: dict) -> None:
        steps = plan.get("plan", [])
        for step in steps:
            app_id = step.get("app_id")
            action = step.get("action")
            params = step.get("params", {})
            desc = step.get("description", "")

            logger.info("动态规划步骤 %s: %s", step.get("step"), desc)

            try:
                if action:
                    await self.registry.call_action(app_id, action, params)
                else:
                    await self.registry.send_intake(app_id, "/intake/dynamic_plan", trigger_event)
            except Exception as e:
                logger.error("动态规划步骤执行失败: %s", e)

    async def _get_context(self) -> dict:
        try:
            from infra import redis_client
            if redis_client.client is None:
                return {}
            keys = await redis_client.client.keys("context:user:*")
            if not keys:
                return {}
            values = await redis_client.client.mget(*keys)
            result = {}
            for key, val in zip(keys, values):
                short = key[len("context:user:"):]
                if val:
                    try:
                        result[short] = json.loads(val)
                    except Exception:
                        result[short] = val
            return result
        except Exception:
            return {}

    def _get_apps_summary(self) -> str:
        lines = []
        for app in self.registry.list_apps():
            actions = [a.get("name", "") for a in app.manifest.capabilities.actions]
            lines.append(f"- {app.id}: actions={actions}")
        return "\n".join(lines) if lines else "无"
