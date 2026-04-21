"""
Reminder App — 提醒助手
创建和管理定时提醒，在合适的时机通过全局弹窗通知用户
支持一次性提醒、重复提醒（daily/weekly/weekday）
感知认知负荷：高负荷时推迟非紧急提醒
"""

import os
import asyncio
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

import sys
sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp, Context, emit
from nervus_sdk.models import Event

nervus = NervusApp("reminder")

DB_PATH = os.getenv("DB_PATH", "/data/reminder.db")
ARBOR_URL = os.getenv("ARBOR_URL", "http://arbor-core:8090")

# ── 数据库初始化 ──────────────────────────────────────────


def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reminders (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                message     TEXT DEFAULT '',
                remind_at   TEXT NOT NULL,
                repeat      TEXT DEFAULT 'none',
                priority    TEXT DEFAULT 'normal',
                active      INTEGER DEFAULT 1,
                snoozed     INTEGER DEFAULT 0,
                fired_count INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_rem_remind ON reminders(remind_at);
            CREATE INDEX IF NOT EXISTS idx_rem_active ON reminders(active, remind_at);
        """)


init_db()


# ── 工具函数 ──────────────────────────────────────────────

def _make_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _next_remind_at(remind_at: str, repeat: str) -> Optional[str]:
    """计算下次提醒时间（重复提醒）"""
    try:
        dt = datetime.fromisoformat(remind_at)
    except Exception:
        return None

    if repeat == "daily":
        return (dt + timedelta(days=1)).isoformat()
    elif repeat == "weekly":
        return (dt + timedelta(weeks=1)).isoformat()
    elif repeat == "weekday":
        next_dt = dt + timedelta(days=1)
        # 跳过周末
        while next_dt.weekday() >= 5:
            next_dt += timedelta(days=1)
        return next_dt.isoformat()
    elif repeat.startswith("hourly"):
        # 支持 "hourly:N" 格式，N 小时
        parts = repeat.split(":")
        hours = int(parts[1]) if len(parts) > 1 else 1
        return (dt + timedelta(hours=hours)).isoformat()
    return None


async def _fire_reminder(reminder_id: str, title: str, message: str, priority: str):
    """触发提醒：调用 Arbor Core 全局弹窗 API"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{ARBOR_URL}/notify/global_popup",
                json={
                    "title": f"提醒：{title}",
                    "message": message or title,
                    "source_app": "reminder",
                    "level": "high" if priority == "high" else "normal",
                }
            )
    except Exception:
        pass

    # 发布到总线
    await emit("schedule.reminder.triggered", {
        "reminder_id": reminder_id,
        "title": title,
        "message": message,
        "fired_at": datetime.utcnow().isoformat(),
    })


async def _check_and_fire():
    """检查到期提醒并触发"""
    now = datetime.utcnow()
    now_str = now.isoformat()

    # 读取认知负荷，决定是否推迟低优先级提醒
    cognitive_load = await Context.get("cognitive.load", "medium")

    with get_db() as conn:
        due = conn.execute(
            "SELECT * FROM reminders WHERE active=1 AND remind_at <= ? ORDER BY remind_at",
            (now_str,)
        ).fetchall()

    for row in due:
        reminder = dict(row)
        reminder_id = reminder["id"]
        priority = reminder.get("priority", "normal")

        # 高负荷时推迟低优先级提醒 15 分钟
        if cognitive_load == "high" and priority == "low":
            new_time = (now + timedelta(minutes=15)).isoformat()
            with get_db() as conn:
                conn.execute(
                    "UPDATE reminders SET remind_at=?, snoozed=snoozed+1 WHERE id=?",
                    (new_time, reminder_id)
                )
            continue

        # 触发提醒
        await _fire_reminder(
            reminder_id,
            reminder["title"],
            reminder["message"],
            priority
        )

        # 计算下次提醒或停用
        repeat = reminder.get("repeat", "none")
        next_at = _next_remind_at(reminder["remind_at"], repeat)

        with get_db() as conn:
            if next_at and repeat != "none":
                conn.execute(
                    "UPDATE reminders SET remind_at=?, fired_count=fired_count+1 WHERE id=?",
                    (next_at, reminder_id)
                )
            else:
                # 一次性提醒：标记为不活跃
                conn.execute(
                    "UPDATE reminders SET active=0, fired_count=fired_count+1 WHERE id=?",
                    (reminder_id,)
                )


async def _reminder_loop():
    """每分钟检查一次到期提醒"""
    await asyncio.sleep(5)  # 启动延迟
    while True:
        try:
            await _check_and_fire()
        except Exception:
            pass
        await asyncio.sleep(60)


# ── 事件订阅 ──────────────────────────────────────────────

@nervus.on("context.user_state.updated")
async def handle_state_update(event: Event):
    """状态变化时无需处理，提醒检查循环会自动读取最新负荷"""
    return {"status": "ok"}


# ── Actions ───────────────────────────────────────────────

@nervus.action("create_reminder")
async def action_create_reminder(payload: dict) -> dict:
    """创建提醒"""
    title = payload.get("title", "").strip()
    remind_at = payload.get("remind_at", "").strip()
    message = payload.get("message", "")
    repeat = payload.get("repeat", "none")
    priority = payload.get("priority", "normal")

    if not title:
        return {"error": "title 不能为空"}
    if not remind_at:
        return {"error": "remind_at 不能为空（ISO 8601 格式，如 2024-01-20T09:00:00）"}

    # 验证时间格式
    try:
        datetime.fromisoformat(remind_at)
    except ValueError:
        return {"error": f"remind_at 格式错误: {remind_at}，需要 ISO 8601"}

    if repeat not in ("none", "daily", "weekly", "weekday") and not repeat.startswith("hourly"):
        return {"error": "repeat 只支持: none, daily, weekly, weekday, hourly:N"}

    reminder_id = _make_id()
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        conn.execute(
            """INSERT INTO reminders (id, title, message, remind_at, repeat, priority, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (reminder_id, title, message, remind_at, repeat, priority, now)
        )

    return {"reminder_id": reminder_id, "status": "created", "remind_at": remind_at}


@nervus.action("snooze_reminder")
async def action_snooze_reminder(payload: dict) -> dict:
    """暂缓提醒"""
    reminder_id = payload.get("reminder_id")
    minutes = int(payload.get("minutes", 10))

    if not reminder_id:
        return {"error": "reminder_id 不能为空"}

    new_time = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()

    with get_db() as conn:
        row = conn.execute("SELECT id FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        if not row:
            return {"error": "提醒不存在"}
        conn.execute(
            "UPDATE reminders SET remind_at=?, snoozed=snoozed+1 WHERE id=?",
            (new_time, reminder_id)
        )

    return {"reminder_id": reminder_id, "remind_at": new_time, "status": "snoozed"}


@nervus.action("list_upcoming")
async def action_list_upcoming(payload: dict) -> dict:
    hours = int(payload.get("hours", 24))
    now = datetime.utcnow()
    end_time = (now + timedelta(hours=hours)).isoformat()

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE active=1 AND remind_at >= ? AND remind_at < ? ORDER BY remind_at",
            (now.isoformat(), end_time)
        ).fetchall()
    return {"reminders": [dict(r) for r in rows]}


@nervus.action("cancel_reminder")
async def action_cancel_reminder(payload: dict) -> dict:
    reminder_id = payload.get("reminder_id")
    if not reminder_id:
        return {"error": "reminder_id 不能为空"}
    with get_db() as conn:
        conn.execute("UPDATE reminders SET active=0 WHERE id=?", (reminder_id,))
    return {"reminder_id": reminder_id, "status": "cancelled"}


# ── REST API ──────────────────────────────────────────────

@nervus._api.get("/reminders")
async def list_reminders(active_only: bool = True, limit: int = 50):
    with get_db() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE active=1 ORDER BY remind_at LIMIT ?",
                (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reminders ORDER BY remind_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
    return {"reminders": [dict(r) for r in rows]}


@nervus._api.post("/reminders")
async def create_reminder_api(body: dict):
    return await action_create_reminder(body)


@nervus._api.get("/reminders/{reminder_id}")
async def get_reminder(reminder_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="提醒不存在")
    return dict(row)


@nervus._api.post("/reminders/{reminder_id}/snooze")
async def snooze_api(reminder_id: str, body: dict):
    body["reminder_id"] = reminder_id
    return await action_snooze_reminder(body)


@nervus._api.delete("/reminders/{reminder_id}")
async def cancel_reminder_api(reminder_id: str):
    return await action_cancel_reminder({"reminder_id": reminder_id})


@nervus._api.get("/upcoming")
async def upcoming_api(hours: int = 24):
    return await action_list_upcoming({"hours": hours})


@nervus._api.post("/reminders/{reminder_id}/fire")
async def manual_fire(reminder_id: str):
    """手动立即触发提醒（调试用）"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="提醒不存在")
    reminder = dict(row)
    await _fire_reminder(reminder_id, reminder["title"], reminder["message"], reminder.get("priority", "normal"))
    return {"status": "fired"}


@nervus.state
async def get_state():
    now = datetime.utcnow()
    next_24h = (now + timedelta(hours=24)).isoformat()
    with get_db() as conn:
        active = conn.execute("SELECT COUNT(*) as c FROM reminders WHERE active=1").fetchone()["c"]
        upcoming = conn.execute(
            "SELECT COUNT(*) as c FROM reminders WHERE active=1 AND remind_at < ?",
            (next_24h,)
        ).fetchone()["c"]
        next_one = conn.execute(
            "SELECT title, remind_at FROM reminders WHERE active=1 ORDER BY remind_at LIMIT 1"
        ).fetchone()
    return {
        "active_reminders": active,
        "upcoming_24h": upcoming,
        "next_reminder": dict(next_one) if next_one else None,
    }


# ── 启动后台任务 ──────────────────────────────────────────

@nervus._api.on_event("startup")
async def startup():
    asyncio.create_task(_reminder_loop())


if __name__ == "__main__":
    nervus.run(port=int(os.getenv("APP_PORT", "8011")))
