"""
Sense App — AI 感知页数据服务
从 Context Graph 实时读取用户状态，供前端感知页展示
"""

import json
import os
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp, Context, emit
from nervus_sdk.models import Event, Manifest

nervus = NervusApp("sense")

# ── 状态感知逻辑 ──────────────────────────────────────────

COGNITIVE_LOAD_SIGNALS = {
    "message_reply_delay": 0.3,    # 消息回复延迟
    "document_revisions": 0.25,    # 文档修改次数
    "meeting_overrun": 0.25,       # 会议超时
    "meal_delay": 0.2,             # 进餐延迟
}


async def compute_cognitive_load() -> dict:
    """根据多信号推断认知负荷"""
    signals = {}
    score = 0.5  # 默认中等

    # 从 Context Graph 读取信号
    last_meal = await Context.get("physical.last_meal")
    recent_meeting = await Context.get("social.recent_meeting")
    calorie_remaining = await Context.get("physical.calorie_remaining", 2000)

    # 进餐延迟信号
    if last_meal:
        try:
            last_meal_dt = datetime.fromisoformat(str(last_meal).replace("Z", ""))
            hours_since_meal = (datetime.utcnow() - last_meal_dt).total_seconds() / 3600
            if hours_since_meal > 5:
                score += 0.15
                signals["meal_delay"] = f"超过 {hours_since_meal:.1f} 小时未进餐"
        except Exception:
            pass

    # 热量剩余（间接反映状态）
    if isinstance(calorie_remaining, (int, float)) and calorie_remaining < 200:
        score += 0.1
        signals["low_calories"] = "今日热量预算即将耗尽"

    # 归一化到 0-1
    score = max(0.0, min(1.0, score))

    if score < 0.35:
        load_level = "low"
        load_label = "轻松"
    elif score < 0.65:
        load_level = "medium"
        load_label = "正常"
    else:
        load_level = "high"
        load_label = "繁重"

    return {
        "load": load_level,
        "label": load_label,
        "score": round(score, 2),
        "signals": signals,
    }


async def get_full_user_state() -> dict:
    """获取完整的用户状态快照（感知页用）"""
    all_context = await Context.get_all_user_state()
    cognitive = await compute_cognitive_load()

    return {
        "cognitive": {
            **cognitive,
            "current_focus": all_context.get("cognitive.current_focus", ""),
            "recent_topics": all_context.get("cognitive.recent_topics", []),
        },
        "physical": {
            "location_type": all_context.get("physical.location_type", ""),
            "activity": all_context.get("physical.activity", ""),
            "last_meal": all_context.get("physical.last_meal", ""),
            "calorie_remaining": all_context.get("physical.calorie_remaining", 0),
            "daily_calorie_budget": all_context.get("physical.daily_calorie_budget", 2000),
            "sleep_last_night": all_context.get("physical.sleep_last_night", 0),
        },
        "temporal": {
            "current_schedule": all_context.get("temporal.current_schedule", ""),
            "upcoming_events": all_context.get("temporal.upcoming_events", []),
            "day_type": all_context.get("temporal.day_type", "workday"),
            "time_of_day": _get_time_of_day(),
        },
        "social": {
            "communication_mode": all_context.get("social.communication_mode", "active"),
            "recent_meeting": all_context.get("social.recent_meeting"),
        },
        "travel": {
            "is_traveling": all_context.get("travel.is_traveling", False),
            "current_trip": all_context.get("travel.current_trip"),
        },
        "updated_at": datetime.utcnow().isoformat(),
    }


def _get_time_of_day() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 9:
        return "morning"
    elif 9 <= hour < 12:
        return "late_morning"
    elif 12 <= hour < 14:
        return "noon"
    elif 14 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 21:
        return "evening"
    else:
        return "night"


# ── 监听状态更新事件 ──────────────────────────────────────

@nervus.on("context.user_state.updated")
async def handle_state_update(event: Event):
    """接收状态更新，重新推断综合状态"""
    payload = event.payload
    field = payload.get("field", "")
    value = payload.get("value")

    if field.startswith("cognitive.") or field.startswith("physical."):
        # 重新推断认知负荷
        new_cognitive = await compute_cognitive_load()
        new_load = new_cognitive["load"]

        # 写入 Context Graph
        await Context.set("cognitive.load", new_load)

    return {"status": "ok"}


@nervus.on("health.calorie.meal_logged")
async def handle_meal_logged(event: Event):
    """饮食记录 → 更新状态"""
    payload = event.payload
    if payload.get("remaining", 0) < 0:
        await Context.set("cognitive.load", "medium")
    return {"status": "ok"}


# ── REST API ──────────────────────────────────────────────

@nervus._api.get("/user-state")
async def user_state():
    """获取完整用户状态（感知页轮询）"""
    return await get_full_user_state()


@nervus._api.get("/cognitive")
async def cognitive_state():
    return await compute_cognitive_load()


@nervus._api.post("/user-state/update")
async def update_state(body: dict):
    """手动更新用户状态字段"""
    field = body.get("field", "")
    value = body.get("value")
    if not field:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="field 不能为空")
    await Context.set(field, value)
    await emit("context.user_state.updated", {"field": field, "value": value})
    return {"status": "ok", "field": field, "value": value}


@nervus.state
async def get_state():
    return await get_full_user_state()


if __name__ == "__main__":
    nervus.run(port=int(os.getenv("APP_PORT", "8005")))
