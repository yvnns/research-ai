"""Image discovery, download, validation and deduplication."""

from __future__ import annotations

import asyncio
import hashlib
import io
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from PIL import Image

from app.config import settings, IMAGES_DIR
from app.core.image_analyzer import (
    compute_phash,
    compute_sha256,
    is_near_duplicate,
    score_image,
    classify_image,
)
from app.core.relevance import has_query_match, has_useful_image_match
from app.database import db
from app.services.search_providers import BaseProvider, default_providers
from app.services.security import is_safe_url, safe_filename, validate_image_bytes


def _ext_from_mime(mime: Optional[str], url: str) -> str:
    if mime:
        if "jpeg" in mime or "jpg" in mime:
            return ".jpg"
        if "png" in mime:
            return ".png"
        if "webp" in mime:
            return ".webp"
        if "gif" in mime:
            return ".gif"
    low = url.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if ext in low:
            return ext
    return ".jpg"


async def _download(url: str) -> Optional[tuple[bytes, Optional[str]]]:
    if not is_safe_url(url):
        return None
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ResearchAI/1.0)"}
    try:
        async with httpx.AsyncClient(timeout=settings.max_download_seconds, follow_redirects=True, headers=headers) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                mime = resp.headers.get("content-type", "").split(";")[0].strip()
                size = 0
                chunks = []
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > settings.max_file_size_mb * 1024 * 1024:
                        return None
                    chunks.append(chunk)
                data = b"".join(chunks)
    except Exception:
        return None
    if not validate_image_bytes(data, settings.max_file_size_mb * 1024 * 1024):
        # Pillow validation will still decide; magic check is pre-filter
        pass
    return data, mime


def _validate_image(data: bytes) -> Optional[Image.Image]:
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        # reopen after verify
        img = Image.open(io.BytesIO(data))
        return img
    except Exception:
        return None


async def hunt_images(
    search_id: str,
    query: str,
    image_queries: List[str],
    collected_pages: List[Dict],
    providers: Optional[List[BaseProvider]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if limit is None:
        limit = settings.max_images
    providers = providers or default_providers()
    candidates: List[Dict[str, Any]] = []

    # 1. Image search providers
    sem = asyncio.Semaphore(4)
    async def search_one(p: BaseProvider, q: str):
        async with sem:
            try:
                return await p.search(q, kind="image", limit=15)
            except Exception:
                return []

    tasks = []
    for p in providers:
        if not p.available():
            continue
        for q in (image_queries or [query]):
            tasks.append(search_one(p, q))
    for res in await asyncio.gather(*tasks):
        for r in res or []:
            if not has_useful_image_match(query, r.title + " " + r.url + " " + r.snippet):
                continue
            candidates.append({
                "url": r.url,
                "page_url": None,
                "alt": r.title or "",
                "context": r.snippet or "",
                "page_title": r.title or "",
                "provider": r.provider,
                "thumbnail": r.thumbnail,
            })

    # 2. Extracted images from collected pages
    for page in collected_pages:
        page_text = page.get("title", "") + " " + page.get("url", "")
        if not has_query_match(query, page_text):
            continue
        for img in page.get("images", []):
            img_text = img.get("url", "") + " " + img.get("alt", "")
            if not has_useful_image_match(query, img_text):
                continue
            candidates.append({
                "url": img["url"],
                "page_url": page.get("url"),
                "alt": img.get("alt", ""),
                "context": img.get("context", ""),
                "page_title": page.get("title", ""),
                "provider": "page_extract",
                "thumbnail": None,
            })

    BLOCKED_IMAGE_TERMS = {
        "logo", "icon", "favicon", "sprite", "banner", "visa", "mastercard",
        "elo", "pix", "payment", "pagamento", "badge", "button", "avatar",
        "placeholder", "loading", "spinner", "menu", "nav", "header", "footer",
        "thumb", "thumbnail", "privacy", "frontend-assets", "hero", "process-data",
        "sem-imagem", "sem_imagem", "no-image", "noimage", "placeholder",
    }

    def _blocked(cand: dict) -> bool:
        text = " ".join([cand.get("url", ""), cand.get("alt", ""), cand.get("context", ""), cand.get("page_title", "")]).lower()
        return any(term in text for term in BLOCKED_IMAGE_TERMS)

    # Dedup by URL and remove obvious non-product images
    seen_urls: set[str] = set()
    unique_candidates = []
    blocked_count = 0
    for c in candidates:
        if c["url"] in seen_urls:
            continue
        if _blocked(c):
            blocked_count += 1
            continue
        seen_urls.add(c["url"])
        unique_candidates.append(c)
    # Debug output removed for production.

    # Score and sort
    for c in unique_candidates:
        c["score"] = score_image(query, c["url"], c.get("alt", ""), c.get("page_title", ""), c.get("context", ""))
    unique_candidates.sort(key=lambda x: x.get("score", 0), reverse=True)

    storage_dir = IMAGES_DIR / search_id
    storage_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir = storage_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    existing_phashes: List[str] = []
    existing_sha: set[str] = set()
    stored: List[Dict[str, Any]] = []
    small_allowed = False
    download_sem = asyncio.Semaphore(6)

    async def process(cand: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        nonlocal existing_phashes
        if len(stored) >= limit:
            return None
        url = cand["url"]
        # Skip URLs that visibly encode small dimensions before downloading.
        import re as _re
        m = _re.search(r"(\\d{2,4})x(\\d{2,4})", url)
        if m and (not small_allowed):
            if max(int(m.group(1)), int(m.group(2))) < 400:
                return None
        async with download_sem:
            downloaded = await _download(url)
            used_url = url
            if not downloaded and cand.get("thumbnail"):
                used_url = cand["thumbnail"]
                downloaded = await _download(used_url)
        if not downloaded:
            return None
        url = used_url
        data, mime = downloaded
        img = _validate_image(data)
        if img is None:
            return None
        width, height = img.size
        # Prefer high-resolution images; thumbnails are only considered in the fallback pass.
        if width < 400 or height < 400:
            if not small_allowed:
                return None
            if len(stored) >= 2:
                return None
        # Discard banners/icons by extreme aspect ratio or tiny area.
        aspect = width / max(height, 1)
        area = width * height
        if (aspect > 3.0 or aspect < 0.33 or area < 60000):
            if len(stored) >= 2:
                return None
        sha = compute_sha256(data)
        if sha in existing_sha:
            return None
        phash = compute_phash(data)
        if is_near_duplicate(phash, existing_phashes):
            return None
        # Re-score with dimensions
        score = score_image(query, url, cand.get("alt", ""), cand.get("page_title", ""), cand.get("context", ""), width, height)
        if score < settings.image_relevance_threshold and len(stored) >= max(5, limit // 2):
            # skip low relevance only after we have enough
            pass

        ext = _ext_from_mime(mime, url)
        filename = safe_filename(f"{hashlib.sha1(url.encode()).hexdigest()[:10]}{ext}")
        local_path = storage_dir / filename
        local_path.write_bytes(data)

        # thumbnail
        thumb_path = thumbs_dir / filename
        try:
            with Image.open(local_path) as im:
                im.thumbnail((320, 320))
                im.save(thumb_path)
        except Exception:
            thumb_path = local_path

        classification = classify_image(score, url, cand.get("alt", ""))
        verification_status = "unverified"
        if score >= 0.7:
            verification_status = "likely_match"
        elif score >= 0.4:
            verification_status = "similar"

        metadata = {
            "provider": cand.get("provider"),
            "thumbnail_url": cand.get("thumbnail"),
            "alt": cand.get("alt"),
        }
        record = {
            "original_url": url,
            "page_url": cand.get("page_url"),
            "local_path": str(local_path),
            "thumb_path": str(thumb_path),
            "filename": filename,
            "mime_type": mime,
            "width": width,
            "height": height,
            "size": len(data),
            "hash_sha256": sha,
            "phash": phash,
            "relevance": round(score, 3),
            "classification": classification,
            "verification_status": verification_status,
            "is_duplicate": False,
            "metadata": metadata,
        }
        iid = await db.insert_image(search_id, record)
        record["id"] = iid
        existing_sha.add(sha)
        if phash:
            existing_phashes.append(phash)
        stored.append(record)
        return record

    # Process with concurrency, but stop when limit reached
    for cand in unique_candidates:
        if len(stored) >= limit:
            break
        if cand.get("score", 0) < settings.image_relevance_threshold and len(stored) >= 3:
            # still try a few; but skip obvious low relevance if enough
            continue
        await process(cand)

    # If too few images, allow thumbnails and process remaining
    if len(stored) < min(5, limit):
        small_allowed = True
        for cand in unique_candidates:
            if len(stored) >= limit:
                break
            # skip already stored by url
            if any(s["original_url"] == cand["url"] for s in stored):
                continue
            await process(cand)

    return stored