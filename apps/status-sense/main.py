"""
Status Sense App — 状态感知仪
多信号融合推断认知负荷，写入 Context Graph，供 Sense 前端和 Calendar、Reminder 读取。

信号来源：
  - physical.activity          活动状态（步行/静止/运动）
  - physical.last_meal         上次进食时间（血糖影响专注力）
  - physical.calorie_remaining 热量预算余量（低余量→压力感）
  - cognitive.focus_duration   持续专注时长（分钟）
  - social.recent_meeting      最近会议（会议密度）
  - temporal.current_hour      当前时段（上午/下午/晚上）
  - temporal.day_type          工作日 or 周末

输出：cognitive.load = low | medium | high
"""

import os
import asyncio
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp, Context, emit
from nervus_sdk.models import Event

nervus = NervusApp("status-sense")

DB_PATH = os.getenv("DB_PATH", "/data/status-sense.db")

# ── 数据库（负荷历史） ──────────────────────────────────

def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS load_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                load       TEXT NOT NULL,
                score      REAL NOT NULL,
                signals    TEXT,
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_lh_time ON load_history(recorded_at DESC);
        """)

init_db()

# ── 负荷计算核心 ──────────────────────────────────────

WEIGHTS = {
    "focus_duration":     0.30,  # 长时专注→负荷上升
    "meeting_recency":    0.25,  # 近期会议→社交耗能
    "meal_gap":           0.20,  # 距上次进食时长→血糖下降
    "time_of_day":        0.15,  # 下午三点低谷
    "calorie_pressure":   0.10,  # 热量余量低→焦虑
}

def _hours_since(iso_str: str) -> float:
    if not iso_str:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_str)
        return max(0.0, (datetime.utcnow() - dt).total_seconds() / 3600)
    except Exception:
        return 0.0

async def _compute_load_score() -> tuple[str, float, dict]:
    """
    读取 Context Graph 的各项信号，计算 0~100 的负荷分，
    映射到 low(<35) / medium(35~65) / high(>65)
    返回 (load_level, score, signals_dict)
    """
    signals = {}

    # 1. 专注时长（分钟）
    focus_min = float(await Context.get("cognitive.focus_duration", 0) or 0)
    # 专注 > 90 分钟开始积压负荷，封顶 120 分钟
    focus_score = min(100, (focus_min / 120) * 100) if focus_min > 0 else 0
    signals["focus_duration_min"] = focus_min

    # 2. 会议新近度
    recent_meeting = await Context.get("social.recent_meeting", None)
    if recent_meeting and isinstance(recent_meeting, dict):
        meeting_ts = recent_meeting.get("timestamp", "")
    else:
        meeting_ts = str(recent_meeting) if recent_meeting else ""
    hours_since_meeting = _hours_since(meeting_ts)
    # 3 小时内开过会 → 社交疲劳
    meeting_score = max(0, 100 - (hours_since_meeting / 3) * 100) if hours_since_meeting < 3 else 0
    signals["hours_since_meeting"] = round(hours_since_meeting, 1)

    # 3. 上次进食时长
    last_meal = await Context.get("physical.last_meal", None)
    meal_gap_h = _hours_since(str(last_meal)) if last_meal else 0
    # 3~5 小时未进食：血糖下降，专注力降低
    if 3 <= meal_gap_h <= 5:
        meal_score = 60 + (meal_gap_h - 3) * 20
    elif meal_gap_h > 5:
        meal_score = 100
    else:
        meal_score = 0
    signals["meal_gap_hours"] = round(meal_gap_h, 1)

    # 4. 时段（下午 14:00~16:00 生理低谷）
    current_hour = int(await Context.get("temporal.current_hour", datetime.utcnow().hour) or datetime.utcnow().hour)
    if 14 <= current_hour <= 16:
        time_score = 70
    elif 22 <= current_hour or current_hour <= 6:
        time_score = 50  # 深夜/凌晨
    else:
        time_score = 10
    signals["current_hour"] = current_hour

    # 5. 热量压力
    calorie_remaining = float(await Context.get("physical.calorie_remaining", 500) or 500)
    # 余量 < 200 kcal → 焦虑
    calorie_score = max(0, min(100, (200 - calorie_remaining) / 2)) if calorie_remaining < 200 else 0
    signals["calorie_remaining"] = calorie_remaining

    # 加权求和
    score = (
        focus_score    * WEIGHTS["focus_duration"]  +
        meeting_score  * WEIGHTS["meeting_recency"] +
        meal_score     * WEIGHTS["meal_gap"]        +
        time_score     * WEIGHTS["time_of_day"]     +
        calorie_score  * WEIGHTS["calorie_pressure"]
    )
    score = round(score, 1)

    if score < 35:
        level = "low"
    elif score < 65:
        level = "medium"
    else:
        level = "high"

    return level, score, signals


async def _update_load():
    """计算负荷并写入 Context，同时记录历史"""
    level, score, signals = await _compute_load_score()
    now = datetime.utcnow().isoformat()

    await Context.set("cognitive.load",            level)
    await Context.set("cognitive.load_score",      score)
    await Context.set("cognitive.load_updated_at", now)

    # 记录到本地数据库
    with get_db() as conn:
        conn.execute(
            "INSERT INTO load_history (load, score, signals, recorded_at) VALUES (?,?,?,?)",
            (level, score, json.dumps(signals), now)
        )
        # 只保留最近 7 天
        conn.execute(
            "DELETE FROM load_history WHERE recorded_at < ?",
            ((datetime.utcnow() - timedelta(days=7)).isoformat(),)
        )

    # 发布状态变化事件（触发 Calendar、Reminder 等订阅者）
    await emit("context.user_state.updated", {
        "field": "cognitive.load",
        "value": level,
        "score": score,
        "signals": signals,
        "updated_at": now,
    })

    return level, score, signals


# ── 事件订阅 ──────────────────────────────────────────

@nervus.on("health.calorie.meal_logged")
async def on_meal(event: Event):
    """进食后立即重新评估（血糖回升）"""
    await _update_load()
    return {"status": "ok"}

@nervus.on("meeting.recording.processed")
async def on_meeting(event: Event):
    """会议结束后重新评估（社交疲劳上升）"""
    await _update_load()
    return {"status": "ok"}

@nervus.on("media.photo.classified")
async def on_photo(event: Event):
    """照片分类后轻量更新（活动状态可能变化）"""
    await _update_load()
    return {"status": "ok"}

@nervus.on("context.user_state.updated")
async def on_state_update(event: Event):
    """其他状态字段更新时重新计算（避免循环：自身发出的事件跳过）"""
    if event.payload.get("field", "").startswith("cognitive.load"):
        return {"status": "skip"}
    await _update_load()
    return {"status": "ok"}


# ── Actions ───────────────────────────────────────────

@nervus.action("compute_load")
async def action_compute_load(payload: dict) -> dict:
    level, score, signals = await _update_load()
    return {"load": level, "score": score, "signals": signals}

@nervus.action("get_history")
async def action_get_history(payload: dict) -> dict:
    hours = int(payload.get("hours", 24))
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT load, score, signals, recorded_at FROM load_history WHERE recorded_at > ? ORDER BY recorded_at",
            (since,)
        ).fetchall()
    history = []
    for r in rows:
        entry = dict(r)
        try:
            entry["signals"] = json.loads(entry["signals"] or "{}")
        except Exception:
            entry["signals"] = {}
        history.append(entry)
    return {"history": history}


# ── REST API ──────────────────────────────────────────

@nervus._api.get("/load")
async def get_current_load():
    level  = await Context.get("cognitive.load", "unknown")
    score  = await Context.get("cognitive.load_score", 0)
    upd_at = await Context.get("cognitive.load_updated_at", "")
    return {"load": level, "score": score, "updated_at": upd_at}

@nervus._api.post("/load/refresh")
async def refresh_load():
    level, score, signals = await _update_load()
    return {"load": level, "score": score, "signals": signals}

@nervus._api.get("/history")
async def load_history_api(hours: int = 24):
    return await action_get_history({"hours": hours})


# ── 后台定时任务（每 5 分钟自动更新） ──────────────────

async def _background_loop():
    await asyncio.sleep(15)  # 启动延迟
    while True:
        try:
            await _update_load()
        except Exception:
            pass
        await asyncio.sleep(300)  # 5 分钟

@nervus._api.on_event("startup")
async def startup():
    asyncio.create_task(_background_loop())


@nervus.state
async def get_state():
    level = await Context.get("cognitive.load", "unknown")
    score = await Context.get("cognitive.load_score", 0)
    return {"load": level, "score": score}


if __name__ == "__main__":
    nervus.run(port=int(os.getenv("APP_PORT", "8013")))
