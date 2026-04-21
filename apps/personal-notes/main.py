"""
Personal Notes App — 个人笔记
创建笔记后自动发布到知识总线，由 knowledge-base 处理向量化
"""

import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp, emit
from nervus_sdk.models import Event

nervus = NervusApp("personal-notes")

# ── 数据库初始化 ──────────────────────────────────────────

DB_PATH = os.getenv("DB_PATH", "/data/personal-notes.db")


def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                tags        TEXT DEFAULT '[]',
                pinned      INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tags (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT UNIQUE NOT NULL,
                color       TEXT DEFAULT '#888888'
            );

            CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at DESC);
        """)


init_db()


# ── 工具函数 ──────────────────────────────────────────────

def _make_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _note_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags", "[]"))
    except Exception:
        d["tags"] = []
    d["pinned"] = bool(d.get("pinned", 0))
    return d


# ── Actions ───────────────────────────────────────────────

@nervus.action("create_note")
async def action_create_note(payload: dict) -> dict:
    """创建笔记并发布到知识总线"""
    title = payload.get("title", "").strip()
    content = payload.get("content", "").strip()
    tags = payload.get("tags", [])

    if not title or not content:
        return {"error": "title 和 content 不能为空"}

    note_id = _make_id()
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        conn.execute(
            "INSERT INTO notes (id, title, content, tags, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (note_id, title, content, json.dumps(tags), now, now)
        )

    # 发布到知识总线，让 knowledge-base 处理向量化
    await emit("knowledge.note.created", {
        "note_id": note_id,
        "title": title,
        "content": content,
        "tags": tags,
        "created_at": now,
    })

    return {"note_id": note_id, "status": "created"}


@nervus.action("update_note")
async def action_update_note(payload: dict) -> dict:
    """更新笔记内容"""
    note_id = payload.get("note_id")
    if not note_id:
        return {"error": "note_id 不能为空"}

    with get_db() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            return {"error": "笔记不存在"}

        title = payload.get("title", row["title"])
        content = payload.get("content", row["content"])
        tags = payload.get("tags", json.loads(row["tags"] or "[]"))
        now = datetime.utcnow().isoformat()

        conn.execute(
            "UPDATE notes SET title=?, content=?, tags=?, updated_at=? WHERE id=?",
            (title, content, json.dumps(tags), now, note_id)
        )

    # 重新发布到知识总线（knowledge-base 会更新向量）
    await emit("knowledge.note.created", {
        "note_id": note_id,
        "title": title,
        "content": content,
        "tags": tags,
        "updated_at": now,
    })

    return {"note_id": note_id, "status": "updated"}


@nervus.action("delete_note")
async def action_delete_note(payload: dict) -> dict:
    """删除笔记"""
    note_id = payload.get("note_id")
    if not note_id:
        return {"error": "note_id 不能为空"}

    with get_db() as conn:
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    return {"note_id": note_id, "status": "deleted"}


@nervus.action("search_notes")
async def action_search_notes(payload: dict) -> dict:
    """本地全文搜索笔记"""
    query = payload.get("query", "").strip()
    limit = int(payload.get("limit", 20))

    with get_db() as conn:
        if query:
            rows = conn.execute(
                "SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notes ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

    return {"notes": [_note_to_dict(r) for r in rows]}


@nervus.action("get_note")
async def action_get_note(payload: dict) -> dict:
    """获取单条笔记"""
    note_id = payload.get("note_id")
    with get_db() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        return {"error": "笔记不存在"}
    return _note_to_dict(row)


# ── REST API ──────────────────────────────────────────────

@nervus._api.get("/notes")
async def list_notes(limit: int = 50, tag: Optional[str] = None, q: Optional[str] = None):
    """获取笔记列表，支持标签过滤和关键词搜索"""
    with get_db() as conn:
        if q:
            rows = conn.execute(
                "SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (f"%{q}%", f"%{q}%", limit)
            ).fetchall()
        elif tag:
            # JSON 数组内搜索（SQLite JSON 支持）
            rows = conn.execute(
                "SELECT * FROM notes WHERE json_each.value = ? "
                "AND id IN (SELECT id FROM notes, json_each(tags)) "
                "ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (tag, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notes ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

    return {"notes": [_note_to_dict(r) for r in rows], "total": len(rows)}


@nervus._api.post("/notes")
async def create_note_api(body: dict):
    """创建笔记"""
    return await action_create_note(body)


@nervus._api.get("/notes/{note_id}")
async def get_note_api(note_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="笔记不存在")
    return _note_to_dict(row)


@nervus._api.put("/notes/{note_id}")
async def update_note_api(note_id: str, body: dict):
    body["note_id"] = note_id
    return await action_update_note(body)


@nervus._api.delete("/notes/{note_id}")
async def delete_note_api(note_id: str):
    return await action_delete_note({"note_id": note_id})


@nervus._api.get("/tags")
async def list_tags():
    with get_db() as conn:
        # 从所有笔记的 tags 字段中聚合唯一标签
        rows = conn.execute("SELECT tags FROM notes").fetchall()
    tag_set = set()
    for row in rows:
        try:
            tags = json.loads(row["tags"] or "[]")
            tag_set.update(tags)
        except Exception:
            pass
    return {"tags": sorted(tag_set)}


@nervus._api.post("/notes/{note_id}/pin")
async def toggle_pin(note_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT pinned FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="笔记不存在")
        new_pinned = 0 if row["pinned"] else 1
        conn.execute("UPDATE notes SET pinned = ? WHERE id = ?", (new_pinned, note_id))
    return {"note_id": note_id, "pinned": bool(new_pinned)}


@nervus.state
async def get_state():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
        recent = conn.execute(
            "SELECT id, title, updated_at FROM notes ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()
    return {
        "total_notes": total,
        "recent": [dict(r) for r in recent],
    }


if __name__ == "__main__":
    nervus.run(port=int(os.getenv("APP_PORT", "8006")))
