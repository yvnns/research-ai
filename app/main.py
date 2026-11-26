"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, settings
from app.database.db import init_db
from app.api.routes import router

STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/debug/fetch", include_in_schema=False)
async def debug_fetch(url: str, ua: str = "ResearchAI/1.0 (contact@example.com)"):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": ua, "Accept": "application/json"})
            return {"status": r.status_code, "len": len(r.text), "preview": r.text[:200]}
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__, "message": str(e)}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> str:
    path = TEMPLATES_DIR / "index.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "<h1>Research AI</h1>"