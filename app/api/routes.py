"""FastAPI routes."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from PIL import Image

from app.config import settings, IMAGES_DIR
from app.core.pipeline import run_search
from app.database import db
from app.models.schemas import SearchRequest, SearchResponse, SearchStatus
from app.services.search_providers import default_providers
from app.services.security import is_safe_url

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}

@router.get("/api/debug/images")
async def debug_images(q: str = "gazin tower") -> dict:
    providers = [p for p in default_providers() if p.name == "bing_images"]
    out = []
    for p in providers:
        rs = await p.search(q, kind="image", limit=10)
        out.append({
            "provider": p.name,
            "count": len(rs),
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet, "thumbnail": r.thumbnail}
                for r in rs
            ],
        })
    return {"query": q, "results": out}


@router.post("/api/search")
async def create_search(req: SearchRequest, background: BackgroundTasks) -> dict:
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Consulta vazia.")
    max_images = req.max_images if req.max_images is not None else settings.max_images
    max_pages = req.max_pages if req.max_pages is not None else settings.max_pages
    max_images = max(1, min(max_images, 200))
    max_pages = max(1, min(max_pages, 100))
    sid = await db.create_search(req.query, req.deep, max_images, max_pages)
    background.add_task(run_search, sid, req.refresh)
    return {"id": sid, "status": "queued"}


@router.get("/api/search/{search_id}")
async def get_search(search_id: str) -> dict:
    search = await db.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Pesquisa não encontrada.")
    result_json = search.get("result_json")
    if result_json:
        try:
            payload = json.loads(result_json)
            return payload
        except json.JSONDecodeError:
            pass
    # Build minimal status payload
    images = await db.list_images(search_id)
    facts = await db.list_facts(search_id)
    sources = await db.list_sources(search_id)
    return {
        "id": search["id"],
        "query": search["query"],
        "status": search["status"],
        "stage": search["stage"],
        "progress": search["progress"],
        "message": search["message"],
        "summary": search.get("summary"),
        "images": [
            {
                "id": im["id"],
                "url": im["original_url"],
                "page_url": im["page_url"],
                "local_url": f"/api/images/{im['id']}/file",
                "thumb_url": f"/api/images/{im['id']}/thumb",
                "filename": im["filename"],
                "mime_type": im["mime_type"],
                "width": im["width"],
                "height": im["height"],
                "size": im["size"],
                "relevance": im["relevance"],
                "classification": im["classification"],
                "verification_status": im["verification_status"],
                "is_duplicate": bool(im["is_duplicate"]),
                "source_id": im["source_id"],
            }
            for im in images
        ],
        "facts": [
            {
                "id": f["id"],
                "key": f["key"],
                "value": f["value"],
                "source_id": f["source_id"],
                "confidence": f["confidence"],
                "status": f["status"],
            }
            for f in facts
        ],
        "sources": [
            {
                "id": s["id"],
                "url": s["url"],
                "title": s["title"],
                "snippet": s["snippet"],
                "provider": s["provider"],
                "confidence": s["confidence"],
            }
            for s in sources
        ],
        "plan": json.loads(search["plan_json"]) if search.get("plan_json") else {},
        "reliability": json.loads(search["reliability_json"]) if search.get("reliability_json") else {},
        "error": search.get("error"),
    }


@router.get("/api/search/{search_id}/status")
async def get_status(search_id: str) -> dict:
    search = await db.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Pesquisa não encontrada.")
    return {
        "id": search["id"],
        "status": search["status"],
        "stage": search["stage"],
        "progress": search["progress"],
        "message": search["message"],
        "error": search.get("error"),
    }


@router.post("/api/search/{search_id}/refresh")
async def refresh_search(search_id: str, background: BackgroundTasks) -> dict:
    search = await db.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Pesquisa não encontrada.")
    await db.update_search(search_id, status="queued", stage="Planejando", progress=0, message="Reexecutando pesquisa.", error=None)
    background.add_task(run_search, search_id, True)
    return {"id": search_id, "status": "queued"}


@router.get("/api/images/{image_id}/file")
async def image_file(image_id: str) -> FileResponse:
    # find in db by scanning? Need lookup. We'll search all? Implement helper.
    img = await _find_image(image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")
    path = Path(img["local_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(path, media_type=img.get("mime_type") or "application/octet-stream", filename=img["filename"])


@router.get("/api/images/{image_id}/thumb")
async def image_thumb(image_id: str) -> FileResponse:
    img = await _find_image(image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")
    thumb = Path(img["thumb_path"]) if img.get("thumb_path") else Path(img["local_path"])
    if not thumb.exists():
        thumb = Path(img["local_path"])
    return FileResponse(thumb, media_type=img.get("mime_type") or "application/octet-stream")


@router.get("/api/downloads/zip")
async def download_zip(search_id: str) -> StreamingResponse:
    search = await db.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Pesquisa não encontrada.")
    images = await db.list_images(search_id)
    if not images:
        raise HTTPException(status_code=404, detail="Sem imagens.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for im in images:
            p = Path(im["local_path"])
            if p.exists():
                zf.write(p, arcname=im["filename"])
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename=images_{search_id}.zip"})


@router.get("/api/history")
async def history(limit: int = 30) -> list:
    searches = await db.list_searches(limit)
    return [
        {
            "id": s["id"],
            "query": s["query"],
            "status": s["status"],
            "stage": s["stage"],
            "progress": s["progress"],
            "created_at": s["created_at"],
            "updated_at": s["updated_at"],
        }
        for s in searches
    ]


async def _find_image(image_id: str) -> Any:
    # Search all searches is expensive; store a simple cache in db? We'll query images table directly.
    async with db.get_db() as conn:
        cur = await conn.execute("SELECT * FROM images WHERE id=?", (image_id,))
        row = await cur.fetchone()
        return dict(row) if row else None