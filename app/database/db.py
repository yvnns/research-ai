"""SQLite persistence layer."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import aiosqlite

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    normalized_query TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    deep INTEGER NOT NULL DEFAULT 1,
    max_images INTEGER,
    max_pages INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT,
    plan_json TEXT,
    result_json TEXT,
    reliability_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    search_id TEXT NOT NULL,
    query TEXT NOT NULL,
    source TEXT,
    cycle INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(search_id) REFERENCES searches(id)
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    search_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    provider TEXT,
    confidence TEXT NOT NULL DEFAULT 'secondary',
    content_text TEXT,
    collected_at TEXT NOT NULL,
    FOREIGN KEY(search_id) REFERENCES searches(id)
);
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    search_id TEXT NOT NULL,
    original_url TEXT NOT NULL,
    page_url TEXT,
    local_path TEXT NOT NULL,
    thumb_path TEXT,
    filename TEXT NOT NULL,
    mime_type TEXT,
    width INTEGER,
    height INTEGER,
    size INTEGER,
    hash_sha256 TEXT,
    phash TEXT,
    relevance REAL NOT NULL DEFAULT 0,
    classification TEXT NOT NULL DEFAULT 'unknown',
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    is_duplicate INTEGER NOT NULL DEFAULT 0,
    source_id TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(search_id) REFERENCES searches(id)
);
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    search_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source_id TEXT,
    confidence TEXT NOT NULL DEFAULT 'inferred',
    status TEXT NOT NULL DEFAULT 'unverified',
    created_at TEXT NOT NULL,
    FOREIGN KEY(search_id) REFERENCES searches(id)
);
CREATE TABLE IF NOT EXISTS cache (
    cache_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    expires_at REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_searches_query ON searches(normalized_query);
CREATE INDEX IF NOT EXISTS idx_images_search ON images(search_id);
CREATE INDEX IF NOT EXISTS idx_facts_search ON facts(search_id);
CREATE INDEX IF NOT EXISTS idx_sources_search ON sources(search_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def create_search(query: str, deep: bool, max_images: Optional[int], max_pages: Optional[int]) -> str:
    sid = new_id("s_")
    now = now_iso()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO searches (id, query, normalized_query, status, stage, progress, message, deep, max_images, max_pages, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, query, query.strip().lower(), "queued", "Planejando", 0, "Pesquisa enfileirada.", 1 if deep else 0, max_images, max_pages, now, now),
        )
        await db.commit()
    return sid


async def update_search(sid: str, **fields: Any) -> None:
    if not fields:
        return
    allowed = {"status", "stage", "progress", "message", "summary", "plan_json", "result_json", "reliability_json", "error"}
    cols = []
    vals = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        cols.append(f"{k}=?")
        vals.append(v)
    if not cols:
        return
    vals.append(now_iso())
    vals.append(sid)
    async with get_db() as db:
        await db.execute(f"UPDATE searches SET {', '.join(cols)}, updated_at=? WHERE id=?", vals)
        await db.commit()


async def get_search(sid: str) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM searches WHERE id=?", (sid,))
        row = await cur.fetchone()
        if not row:
            return None
        return dict(row)


async def list_searches(limit: int = 50) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM searches ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def insert_query(search_id: str, query: str, source: str = "planner", cycle: int = 0) -> str:
    qid = new_id("q_")
    async with get_db() as db:
        await db.execute(
            "INSERT INTO queries (id, search_id, query, source, cycle, created_at) VALUES (?,?,?,?,?,?)",
            (qid, search_id, query, source, cycle, now_iso()),
        )
        await db.commit()
    return qid


async def insert_source(search_id: str, url: str, title: Optional[str], snippet: Optional[str], provider: Optional[str], confidence: str = "secondary", content_text: Optional[str] = None) -> str:
    sid = new_id("src_")
    async with get_db() as db:
        await db.execute(
            """INSERT INTO sources (id, search_id, url, title, snippet, provider, confidence, content_text, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (sid, search_id, url, title, snippet, provider, confidence, content_text, now_iso()),
        )
        await db.commit()
    return sid


async def list_sources(search_id: str) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM sources WHERE search_id=? ORDER BY collected_at", (search_id,))
        return [dict(r) for r in await cur.fetchall()]


async def insert_image(search_id: str, data: Dict[str, Any]) -> str:
    iid = new_id("img_")
    async with get_db() as db:
        await db.execute(
            """INSERT INTO images (id, search_id, original_url, page_url, local_path, thumb_path, filename, mime_type, width, height, size, hash_sha256, phash, relevance, classification, verification_status, is_duplicate, source_id, metadata_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                iid,
                search_id,
                data["original_url"],
                data.get("page_url"),
                data["local_path"],
                data.get("thumb_path"),
                data["filename"],
                data.get("mime_type"),
                data.get("width"),
                data.get("height"),
                data.get("size"),
                data.get("hash_sha256"),
                data.get("phash"),
                data.get("relevance", 0.0),
                data.get("classification", "unknown"),
                data.get("verification_status", "unverified"),
                1 if data.get("is_duplicate") else 0,
                data.get("source_id"),
                json.dumps(data.get("metadata", {}), ensure_ascii=False),
                now_iso(),
            ),
        )
        await db.commit()
    return iid


async def list_images(search_id: str) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM images WHERE search_id=? ORDER BY relevance DESC, created_at", (search_id,))
        return [dict(r) for r in await cur.fetchall()]


async def insert_fact(search_id: str, key: str, value: str, source_id: Optional[str], confidence: str, status: str = "unverified") -> str:
    fid = new_id("fact_")
    async with get_db() as db:
        await db.execute(
            "INSERT INTO facts (id, search_id, key, value, source_id, confidence, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (fid, search_id, key, value, source_id, confidence, status, now_iso()),
        )
        await db.commit()
    return fid


async def update_fact(fid: str, confidence: Optional[str] = None, status: Optional[str] = None) -> None:
    cols = []
    vals = []
    if confidence is not None:
        cols.append("confidence=?")
        vals.append(confidence)
    if status is not None:
        cols.append("status=?")
        vals.append(status)
    if not cols:
        return
    vals.append(fid)
    async with get_db() as db:
        await db.execute(f"UPDATE facts SET {', '.join(cols)} WHERE id=?", vals)
        await db.commit()


async def list_facts(search_id: str) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM facts WHERE search_id=? ORDER BY created_at", (search_id,))
        return [dict(r) for r in await cur.fetchall()]


async def cache_get(key: str) -> Optional[Any]:
    async with get_db() as db:
        cur = await db.execute("SELECT value_json, expires_at FROM cache WHERE cache_key=?", (key,))
        row = await cur.fetchone()
        if not row:
            return None
        if time.time() > row["expires_at"]:
            await db.execute("DELETE FROM cache WHERE cache_key=?", (key,))
            await db.commit()
            return None
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return None


async def cache_set(key: str, value: Any, ttl_hours: int) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO cache (cache_key, value_json, expires_at, created_at) VALUES (?,?,?,?)",
            (key, json.dumps(value, ensure_ascii=False), time.time() + ttl_hours * 3600, now_iso()),
        )
        await db.commit()