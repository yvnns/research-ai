"""Collect and parse web pages."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services.security import is_safe_url


_PAGE_CACHE: dict[str, Dict] = {}
_PAGE_CACHE_MAX = 120


async def _fetch_page(url: str) -> Optional[Dict]:
    if url in _PAGE_CACHE:
        return _PAGE_CACHE[url]
    if not is_safe_url(url):
        return None
    low = url.lower()
    if any(k in low for k in ("/login", "/signin", "/cart", "/checkout", "/account", "/wp-admin", ".css", ".js", ".ico")):
        return None
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ResearchAI/1.0)"}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True, headers=headers) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type and "application/xhtml" not in content_type and "text/plain" not in content_type:
                    # Still allow if small; collector focuses on HTML/text
                    if "pdf" not in content_type:
                        return None
                chunks = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > settings.max_content_length:
                        break
                    chunks.append(chunk)
                data = b"".join(chunks)
    except Exception:
        return None

    result = {
        "url": str(resp.url),
        "status_code": resp.status_code,
        "content_type": content_type,
        "raw": data,
        "title": "",
        "text": "",
        "links": [],
        "images": [],
        "tables": [],
    }

    if "pdf" in content_type or url.lower().endswith(".pdf"):
        result["is_pdf"] = True
        return result

    try:
        html = data.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        html = data.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    result["soup"] = soup
    result["html"] = html
    title_tag = soup.find("title")
    result["title"] = title_tag.get_text(strip=True) if title_tag else ""
    # Remove scripts/styles
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    result["text"] = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    base = result["url"]
    links: List[str] = []
    seen_links: Set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        if href.startswith("http") and is_safe_url(href) and href not in seen_links:
            seen_links.add(href)
            links.append(href)
    result["links"] = links[:100]

    images: List[Dict] = []
    seen_imgs: Set[str] = set()
    def add_img(src: Optional[str], alt: str = "", context: str = ""):
        if not src:
            return
        src = urljoin(base, src.strip())
        if not src.startswith("http") or not is_safe_url(src):
            return
        if src in seen_imgs:
            return
        seen_imgs.add(src)
        images.append({"url": src, "alt": alt, "context": context})

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        srcset = img.get("srcset")
        if srcset:
            candidates = []
            for part in srcset.split(","):
                pieces = part.strip().split()
                if pieces:
                    candidates.append(pieces[0])
            if candidates:
                src = candidates[-1]
        parent_href = None
        parent = img.find_parent("a")
        if parent and parent.get("href"):
            parent_href = urljoin(base, parent["href"])
        alt = img.get("alt", "") or img.get("title", "")
        # Prefer a parent link only when it clearly points to an image file.
        if parent_href and is_safe_url(parent_href) and any(parent_href.lower().split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
            add_img(parent_href, alt, "parent_image")
        else:
            add_img(src, alt, img.get("title", ""))

    for meta_name in ("og:image", "twitter:image", "twitter:image:src"):
        meta = soup.find("meta", attrs={"property": meta_name}) or soup.find("meta", attrs={"name": meta_name})
        if meta and meta.get("content"):
            add_img(meta["content"], "og:image")

    # JSON-LD image fields (simple regex)
    for m in re.finditer(r'"image"\s*:\s*"([^"]+)"', html):
        add_img(m.group(1), "jsonld")
    result["images"] = images

    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    result["tables"] = tables
    return result


async def collect_pages(urls: List[str], limit: Optional[int] = None) -> List[Dict]:
    if limit is None:
        limit = settings.max_pages
    urls = [u for u in urls if is_safe_url(u)][:limit]
    import asyncio

    sem = asyncio.Semaphore(8)
    async def worker(u):
        async with sem:
            return await fetch_page(u)
    import asyncio

    tasks = [worker(u) for u in urls]
    pages = await asyncio.gather(*tasks)
    return [p for p in pages if p]


def extract_links_for_deepening(page: Dict, query_terms: List[str], limit: int = 5) -> List[str]:
    terms = [t.lower() for t in query_terms if t]
    links = page.get("links", [])
    scored = []
    for link in links:
        score = 0
        low = link.lower()
        for term in terms:
            if term in low:
                score += 2
        if any(k in low for k in ("product", "produto", "catalog", "catalogo", "ficha", "spec", "manual", "pdf")):
            score += 1
        scored.append((score, link))
    scored.sort(reverse=True)
    return [l for _, l in scored[:limit]]
async def fetch_page(url: str) -> Optional[Dict]:
    if url in _PAGE_CACHE:
        return _PAGE_CACHE[url]
    result = await _fetch_page(url)
    if result is not None and len(_PAGE_CACHE) < _PAGE_CACHE_MAX:
        _PAGE_CACHE[url] = result
    return result
