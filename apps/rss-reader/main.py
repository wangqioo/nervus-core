"""
RSS Reader App — RSS 订阅阅读器
定时拉取 RSS/Atom 源，将新文章发布到知识总线
支持：RSS 2.0, Atom, RDF
"""

import os
import asyncio
import sqlite3
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

import sys
sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp, emit
from nervus_sdk.models import Event

nervus = NervusApp("rss-reader")

DB_PATH = os.getenv("DB_PATH", "/data/rss-reader.db")
FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL", "3600"))  # 默认每小时拉取一次

# ── 数据库初始化 ──────────────────────────────────────────


def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feeds (
                id          TEXT PRIMARY KEY,
                url         TEXT UNIQUE NOT NULL,
                title       TEXT,
                description TEXT,
                last_fetched TEXT,
                article_count INTEGER DEFAULT 0,
                active      INTEGER DEFAULT 1,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS articles (
                id          TEXT PRIMARY KEY,
                feed_id     TEXT NOT NULL,
                guid        TEXT,
                title       TEXT,
                url         TEXT,
                content     TEXT,
                summary     TEXT,
                author      TEXT,
                published_at TEXT,
                fetched_at  TEXT NOT NULL,
                published   INTEGER DEFAULT 0,
                UNIQUE(feed_id, guid)
            );

            CREATE INDEX IF NOT EXISTS idx_articles_fetched ON articles(fetched_at DESC);
            CREATE INDEX IF NOT EXISTS idx_articles_feed ON articles(feed_id);
        """)


init_db()


# ── RSS 解析 ──────────────────────────────────────────────

def _make_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _guid(feed_id: str, url_or_id: str) -> str:
    """生成稳定的文章唯一 ID"""
    return hashlib.md5(f"{feed_id}:{url_or_id}".encode()).hexdigest()


def _parse_feed(content: str, feed_url: str) -> tuple[dict, list[dict]]:
    """
    解析 RSS/Atom XML，返回 (feed_meta, articles_list)
    使用 feedparser 库（轻量级）
    """
    try:
        import feedparser
    except ImportError:
        raise RuntimeError("未安装 feedparser，请执行: pip install feedparser")

    parsed = feedparser.parse(content)
    feed = parsed.feed

    feed_meta = {
        "title": feed.get("title", ""),
        "description": feed.get("description", feed.get("subtitle", "")),
    }

    articles = []
    for entry in parsed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title") or _make_id()
        title = entry.get("title", "")
        url = entry.get("link", "")

        # 优先取 content，其次 summary
        content_text = ""
        if hasattr(entry, "content") and entry.content:
            content_text = entry.content[0].get("value", "")
        if not content_text:
            content_text = entry.get("summary", "")

        # 发布时间
        published_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
        if not published_at and hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                published_at = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass

        author = entry.get("author", "")

        articles.append({
            "guid": guid,
            "title": title,
            "url": url,
            "content": content_text,
            "summary": entry.get("summary", "")[:500],
            "author": author,
            "published_at": published_at,
        })

    return feed_meta, articles


async def _fetch_and_process_feed(feed_id: str, feed_url: str) -> dict:
    """拉取单个 RSS 源并处理新文章"""
    now = datetime.utcnow().isoformat()
    new_count = 0

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(feed_url, headers={"User-Agent": "Nervus/1.0 RSS Reader"})
            resp.raise_for_status()
            content = resp.text

        feed_meta, articles = _parse_feed(content, feed_url)

        # 更新 feed 元数据
        with get_db() as conn:
            conn.execute(
                "UPDATE feeds SET title=?, description=?, last_fetched=? WHERE id=?",
                (feed_meta["title"], feed_meta["description"], now, feed_id)
            )

        # 插入新文章（跳过已存在的）
        for article in articles:
            uid = _guid(feed_id, article["guid"])
            try:
                with get_db() as conn:
                    conn.execute(
                        """INSERT OR IGNORE INTO articles
                           (id, feed_id, guid, title, url, content, summary, author, published_at, fetched_at, published)
                           VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
                        (uid, feed_id, article["guid"], article["title"], article["url"],
                         article["content"], article["summary"], article["author"],
                         article["published_at"], now)
                    )
                    # 检查是否真的插入了（rowcount > 0 means new）
                    rows_changed = conn.execute("SELECT changes()").fetchone()[0]

                if rows_changed > 0:
                    new_count += 1
                    # 发布到知识总线
                    await emit("knowledge.article.fetched", {
                        "article_id": uid,
                        "feed_id": feed_id,
                        "feed_url": feed_url,
                        "feed_title": feed_meta["title"],
                        "title": article["title"],
                        "url": article["url"],
                        "content": article["content"][:6000],
                        "summary": article["summary"],
                        "author": article["author"],
                        "published_at": article["published_at"],
                        "fetched_at": now,
                    })
                    # 标记已发布
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE articles SET published=1 WHERE id=?", (uid,)
                        )

            except Exception:
                pass

        # 更新文章总数
        with get_db() as conn:
            conn.execute(
                "UPDATE feeds SET article_count = (SELECT COUNT(*) FROM articles WHERE feed_id=?) WHERE id=?",
                (feed_id, feed_id)
            )

        return {"feed_id": feed_id, "new_articles": new_count, "status": "ok"}

    except Exception as e:
        return {"feed_id": feed_id, "status": "error", "error": str(e)}


# ── 后台定时拉取任务 ──────────────────────────────────────

async def _background_fetch_loop():
    """定期拉取所有活跃 RSS 源"""
    await asyncio.sleep(10)  # 启动后等待 10 秒再开始
    while True:
        with get_db() as conn:
            feeds = conn.execute(
                "SELECT id, url FROM feeds WHERE active = 1"
            ).fetchall()

        for feed in feeds:
            await _fetch_and_process_feed(feed["id"], feed["url"])

        await asyncio.sleep(FETCH_INTERVAL)


# ── Actions ───────────────────────────────────────────────

@nervus.action("fetch_feed")
async def action_fetch_feed(payload: dict) -> dict:
    """手动拉取一个 RSS 源（不需要提前添加）"""
    url = payload.get("url", "").strip()
    if not url:
        return {"error": "url 不能为空"}

    # 先确保 feed 记录存在
    with get_db() as conn:
        row = conn.execute("SELECT id FROM feeds WHERE url = ?", (url,)).fetchone()
        if row:
            feed_id = row["id"]
        else:
            feed_id = _make_id()
            conn.execute(
                "INSERT INTO feeds (id, url, active, created_at) VALUES (?,?,1,?)",
                (feed_id, url, datetime.utcnow().isoformat())
            )

    return await _fetch_and_process_feed(feed_id, url)


@nervus.action("add_feed")
async def action_add_feed(payload: dict) -> dict:
    """添加 RSS 订阅源"""
    url = payload.get("url", "").strip()
    if not url:
        return {"error": "url 不能为空"}

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM feeds WHERE url = ?", (url,)).fetchone()
        if existing:
            return {"feed_id": existing["id"], "status": "already_exists"}

        feed_id = _make_id()
        conn.execute(
            "INSERT INTO feeds (id, url, active, created_at) VALUES (?,?,1,?)",
            (feed_id, url, datetime.utcnow().isoformat())
        )

    # 立即拉取一次
    result = await _fetch_and_process_feed(feed_id, url)
    result["feed_id"] = feed_id
    result["status"] = "added"
    return result


@nervus.action("remove_feed")
async def action_remove_feed(payload: dict) -> dict:
    feed_id = payload.get("feed_id")
    if not feed_id:
        return {"error": "feed_id 不能为空"}
    with get_db() as conn:
        conn.execute("UPDATE feeds SET active = 0 WHERE id = ?", (feed_id,))
    return {"feed_id": feed_id, "status": "removed"}


# ── REST API ──────────────────────────────────────────────

@nervus._api.get("/feeds")
async def list_feeds_api():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, url, title, description, last_fetched, article_count, active FROM feeds ORDER BY created_at DESC"
        ).fetchall()
    return {"feeds": [dict(r) for r in rows]}


@nervus._api.post("/feeds")
async def add_feed_api(body: dict):
    return await action_add_feed(body)


@nervus._api.delete("/feeds/{feed_id}")
async def remove_feed_api(feed_id: str):
    return await action_remove_feed({"feed_id": feed_id})


@nervus._api.post("/feeds/{feed_id}/fetch")
async def fetch_feed_now(feed_id: str):
    """立即触发拉取指定源"""
    with get_db() as conn:
        row = conn.execute("SELECT url FROM feeds WHERE id = ?", (feed_id,)).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="订阅源不存在")
    return await _fetch_and_process_feed(feed_id, row["url"])


@nervus._api.get("/articles")
async def list_articles(limit: int = 30, feed_id: Optional[str] = None):
    with get_db() as conn:
        if feed_id:
            rows = conn.execute(
                "SELECT id, feed_id, title, url, summary, author, published_at, fetched_at "
                "FROM articles WHERE feed_id=? ORDER BY fetched_at DESC LIMIT ?",
                (feed_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, feed_id, title, url, summary, author, published_at, fetched_at "
                "FROM articles ORDER BY fetched_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
    return {"articles": [dict(r) for r in rows]}


@nervus._api.get("/articles/{article_id}")
async def get_article(article_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="文章不存在")
    return dict(row)


@nervus.state
async def get_state():
    with get_db() as conn:
        feed_count = conn.execute("SELECT COUNT(*) as c FROM feeds WHERE active=1").fetchone()["c"]
        article_count = conn.execute("SELECT COUNT(*) as c FROM articles").fetchone()["c"]
        recent = conn.execute(
            "SELECT title, url FROM articles ORDER BY fetched_at DESC LIMIT 5"
        ).fetchall()
    return {
        "active_feeds": feed_count,
        "total_articles": article_count,
        "recent_articles": [dict(r) for r in recent],
    }


# ── 启动后台任务 ──────────────────────────────────────────

@nervus._api.on_event("startup")
async def startup():
    asyncio.create_task(_background_fetch_loop())


if __name__ == "__main__":
    nervus.run(port=int(os.getenv("APP_PORT", "8009")))
