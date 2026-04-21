"""
人生记忆库 App
把你的一生存进一个盒子里
自动归档照片 / 旅行时刻 / 会议记录，生成旅行日志和年度回忆录
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

import sys
sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp, Context, emit
from nervus_sdk.models import Event, Manifest
from nervus_sdk.memory import MemoryGraph

nervus = NervusApp("life-memory")
with open(Path(__file__).parent / "manifest.json") as f:
    nervus.set_manifest(Manifest(**json.load(f)))

DB_PATH = os.getenv("DB_PATH", "/data/life-memory.db")

# 旅行检测阈值：连续 N 张标记为 outdoor/travel 的照片
TRAVEL_PHOTO_THRESHOLD = 3


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS life_moments (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL,   -- photo / meeting / note / trip_moment
            title       TEXT,
            description TEXT,
            photo_path  TEXT,
            tags        TEXT,            -- JSON
            trip_id     TEXT,
            source_app  TEXT,
            timestamp   TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trips (
            id          TEXT PRIMARY KEY,
            name        TEXT,
            start_date  TEXT,
            end_date    TEXT,
            cover_photo TEXT,
            log_text    TEXT,            -- AI 生成的旅行日志
            moments_count INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'active',  -- active / completed
            created_at  TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── 旅行检测 ──────────────────────────────────────────────

async def detect_travel_start(tags: list) -> bool:
    """检测是否开始旅行"""
    travel_tags = {"outdoor", "travel", "beach", "mountain", "city", "nature", "vehicle"}
    is_travel = bool(travel_tags & set(tags))

    if not is_travel:
        return False

    is_traveling = await Context.get("travel.is_traveling", False)
    if is_traveling:
        return False

    # 计算最近 TRAVEL_PHOTO_THRESHOLD 张是否都是旅行照片
    # 简化：只要当前照片是旅行类，就判定为旅行开始
    return True


async def get_or_create_trip() -> str:
    """获取当前旅行 ID，不存在则创建"""
    current_trip = await Context.get("travel.current_trip")
    if current_trip and isinstance(current_trip, dict):
        return current_trip.get("id", "")

    trip_id = str(uuid.uuid4())
    today = date.today().isoformat()
    trip_name = f"{today} 旅行"

    with get_db() as conn:
        conn.execute("""
            INSERT INTO trips (id, name, start_date, status, created_at)
            VALUES (?, ?, ?, 'active', ?)
        """, (trip_id, trip_name, today, datetime.utcnow().isoformat()))
        conn.commit()

    await Context.set("travel.is_traveling", True)
    await Context.set("travel.current_trip", {
        "id": trip_id, "name": trip_name, "start_date": today, "moments_count": 0
    })

    return trip_id


# ── 事件处理 ──────────────────────────────────────────────

@nervus.on("media.photo.classified")
async def handle_photo(event: Event):
    """所有分类过的照片都归入生命记忆流"""
    payload = event.payload
    photo_path = payload.get("photo_path", "")
    tags = payload.get("tags", [])
    timestamp = payload.get("timestamp", str(datetime.utcnow()))

    moment_id = str(uuid.uuid4())
    is_travel = await detect_travel_start(tags)
    trip_id = None

    if is_travel:
        trip_id = await get_or_create_trip()

    with get_db() as conn:
        conn.execute("""
            INSERT INTO life_moments (id, type, photo_path, tags, trip_id, source_app, timestamp, created_at)
            VALUES (?, 'photo', ?, ?, ?, 'photo-scanner', ?, ?)
        """, (moment_id, photo_path, json.dumps(tags), trip_id, timestamp, datetime.utcnow().isoformat()))
        if trip_id:
            conn.execute("UPDATE trips SET moments_count = moments_count + 1 WHERE id = ?", (trip_id,))
        conn.commit()

    # 写入 Memory Graph
    await MemoryGraph.write_life_event(
        type="photo",
        title=f"照片 - {', '.join(tags[:3])}",
        timestamp=datetime.fromisoformat(timestamp.replace("Z", "")),
        source_app="life-memory",
        metadata={"photo_path": photo_path, "tags": tags, "trip_id": trip_id},
    )

    return {"moment_id": moment_id, "trip_id": trip_id}


@nervus.on("memory.travel.moment_captured")
async def handle_travel_moment(event: Event):
    """旅行时刻专门处理"""
    payload = event.payload
    trip_id = await get_or_create_trip()
    await action_add_to_trip(
        photo_path=payload.get("photo_path", ""),
        location_type=payload.get("location_type", "outdoor"),
        timestamp=payload.get("timestamp", str(datetime.utcnow())),
    )
    return {"status": "ok", "trip_id": trip_id}


@nervus.on("meeting.recording.processed")
async def handle_meeting(event: Event):
    """会议记录归入生命流"""
    payload = event.payload
    moment_id = str(uuid.uuid4())
    title = payload.get("title", "会议")
    timestamp = payload.get("timestamp_range", {}).get("start", str(datetime.utcnow()))

    with get_db() as conn:
        conn.execute("""
            INSERT INTO life_moments (id, type, title, source_app, timestamp, created_at)
            VALUES (?, 'meeting', ?, 'meeting-notes', ?, ?)
        """, (moment_id, title, timestamp, datetime.utcnow().isoformat()))
        conn.commit()

    await MemoryGraph.write_life_event(
        type="meeting",
        title=title,
        timestamp=datetime.utcnow(),
        source_app="life-memory",
        metadata={"meeting_id": payload.get("meeting_id")},
    )
    return {"moment_id": moment_id}


# ── Actions ───────────────────────────────────────────────

@nervus.action("archive_moment")
async def action_archive_moment(photo_path: str = "", tags: list = None, timestamp: str = ""):
    tags = tags or []
    ts = timestamp or datetime.utcnow().isoformat()
    moment_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute("""
            INSERT INTO life_moments (id, type, photo_path, tags, timestamp, created_at)
            VALUES (?, 'photo', ?, ?, ?, ?)
        """, (moment_id, photo_path, json.dumps(tags), ts, datetime.utcnow().isoformat()))
        conn.commit()
    return {"event_id": moment_id}


@nervus.action("add_to_trip")
async def action_add_to_trip(photo_path: str = "", location_type: str = "", timestamp: str = ""):
    trip_id = await get_or_create_trip()
    moment_id = str(uuid.uuid4())
    ts = timestamp or datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO life_moments (id, type, photo_path, tags, trip_id, timestamp, created_at)
            VALUES (?, 'trip_moment', ?, ?, ?, ?, ?)
        """, (moment_id, photo_path, json.dumps([location_type]), trip_id, ts, datetime.utcnow().isoformat()))
        conn.execute("UPDATE trips SET moments_count = moments_count + 1 WHERE id = ?", (trip_id,))
        conn.commit()
    return {"trip_id": trip_id, "moment_id": moment_id}


@nervus.action("generate_trip_log")
async def action_generate_trip_log(trip_id: str = ""):
    with get_db() as conn:
        trip = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        moments = conn.execute(
            "SELECT * FROM life_moments WHERE trip_id = ? ORDER BY timestamp ASC", (trip_id,)
        ).fetchall()

    if not trip:
        return {"error": "旅行不存在"}

    moments_desc = "\n".join([
        f"- {m['timestamp']}: {m['type']} {', '.join(json.loads(m['tags'] or '[]'))}"
        for m in moments[:30]
    ])

    prompt = f"""根据以下旅行时刻，写一篇生动的旅行日志（500-800字）：

旅行：{trip['name']}
日期：{trip['start_date']} ~ {trip['end_date'] or '进行中'}
时刻记录：
{moments_desc}

用第一人称，写出旅途的感受和亮点，文字要有温度。"""

    try:
        log_text = await nervus.llm.chat(prompt, temperature=0.7, max_tokens=1000)
    except Exception as e:
        log_text = f"旅行日志生成失败: {e}"

    with get_db() as conn:
        conn.execute("UPDATE trips SET log_text = ? WHERE id = ?", (log_text, trip_id))
        conn.commit()

    await emit("memory.travel.trip_compiled", {"trip_id": trip_id, "name": trip["name"]})

    return {"trip_id": trip_id, "trip_log": log_text}


@nervus.action("get_timeline")
async def action_get_timeline(start_date: str = "", end_date: str = "", limit: int = 50):
    conditions = []
    params = []
    if start_date:
        conditions.append("timestamp >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("timestamp <= ?")
        params.append(end_date)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM life_moments {where} ORDER BY timestamp DESC LIMIT ?",
            params
        ).fetchall()
    return {"events": [dict(r) for r in rows]}


@nervus.state
async def get_state():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM life_moments").fetchone()["c"]
        active_trip = conn.execute(
            "SELECT * FROM trips WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return {
        "total_moments": total,
        "active_trip": dict(active_trip) if active_trip else None,
    }


# ── REST API ──────────────────────────────────────────────

@nervus._api.get("/timeline")
async def timeline(limit: int = 50):
    return await action_get_timeline(limit=limit)


@nervus._api.get("/trips")
async def list_trips():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM trips ORDER BY created_at DESC").fetchall()
    return {"trips": [dict(r) for r in rows]}


@nervus._api.post("/trips/{trip_id}/generate-log")
async def generate_log(trip_id: str):
    return await action_generate_trip_log(trip_id=trip_id)


if __name__ == "__main__":
    init_db()
    nervus.run(port=int(os.getenv("APP_PORT", "8004")))
