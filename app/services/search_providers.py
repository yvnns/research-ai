"""Pluggable search providers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import List, Optional
from urllib.parse import quote_plus, urlencode

import httpx

from app.config import settings
from app.core.relevance import has_query_match
from app.services.security import is_safe_url


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    provider: str = ""
    thumbnail: Optional[str] = None
    kind: str = "text"

    def to_dict(self) -> dict:
        return asdict(self)


class BaseProvider:
    name: str = "base"

    def available(self) -> bool:
        return True

    async def search(self, query: str, kind: str = "text", limit: int = 10) -> List[SearchResult]:
        raise NotImplementedError


class SearXNGProvider(BaseProvider):
    name = "searxng"

    def available(self) -> bool:
        return bool(settings.searxng_url)

    async def search(self, query: str, kind: str = "text", limit: int = 10) -> List[SearchResult]:
        if not self.available():
            return []
        category = "images" if kind == "image" else "general"
        params = {"q": query, "format": "json", "categories": category, "language": "auto"}
        url = settings.searxng_url.rstrip("/") + "/search?" + urlencode(params)
        if not is_safe_url(url):
            return []
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []
        results = []
        for item in data.get("results", [])[:limit]:
            item_url = item.get("url")
            if not item_url or not is_safe_url(item_url):
                continue
            results.append(SearchResult(
                title=item.get("title") or item_url,
                url=item_url,
                snippet=item.get("content") or "",
                provider=self.name,
                thumbnail=item.get("thumbnail") or item.get("img_src"),
                kind=kind,
            ))
        return results


class DuckDuckGoHTMLProvider(BaseProvider):
    name = "duckduckgo_html"

    def available(self) -> bool:
        return True

    async def search(self, query: str, kind: str = "text", limit: int = 10) -> List[SearchResult]:
        if kind == "image":
            return []
        target = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        if not is_safe_url(target):
            return []
        html = ""
        fetch_url = target
        if settings.search_proxy_url:
            fetch_url = settings.search_proxy_url + "?url=" + quote_plus(target)
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
                if settings.search_proxy_url:
                    resp = await client.get(fetch_url)
                else:
                    resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
                resp.raise_for_status()
                html = resp.text
        except Exception:
            html = ""
        if not html or ".result" not in html:
            jina_url = "https://r.jina.ai/https://html.duckduckgo.com/html/?q=" + quote_plus(query)
            try:
                async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html", "X-Return-Format": "html"}) as client:
                    resp = await client.get(jina_url)
                    resp.raise_for_status()
                    html = resp.text
            except Exception:
                html = ""
        if not html:
            return []
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        results = []
        for result in soup.select(".result"):
            a = result.select_one(".result__a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            # DuckDuckGo redirect wrapper
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                from urllib.parse import unquote

                href = unquote(m.group(1))
            if not is_safe_url(href):
                continue
            snippet_el = result.select_one(".result__snippet")
            results.append(SearchResult(
                title=a.get_text(" ", strip=True),
                url=href,
                snippet=snippet_el.get_text(" ", strip=True) if snippet_el else "",
                provider=self.name,
                kind="text",
            ))
            if len(results) >= limit:
                break
        return results


class BingHTMLProvider(BaseProvider):
    name = "bing_html"

    def available(self) -> bool:
        return True

    async def search(self, query: str, kind: str = "text", limit: int = 10) -> List[SearchResult]:
        if kind == "image":
            return []
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = await client.get("https://www.bing.com/search", params={"q": query, "count": limit})
                resp.raise_for_status()
                html = resp.text
        except Exception:
            return []
        from bs4 import BeautifulSoup
        from urllib.parse import parse_qs, urlparse, unquote
        import base64

        def resolve_bing(url: str) -> str:
            try:
                p = urlparse(url)
                if "bing.com" in (p.netloc or "").lower() and p.path.startswith("/ck/a"):
                    qs = parse_qs(p.query)
                    tok = (qs.get("u") or [""])[0]
                    if tok.startswith("a1"):
                        tok = tok[2:]
                    tok += "=" * ((4 - len(tok) % 4) % 4)
                    dec = base64.urlsafe_b64decode(tok).decode("utf-8", "ignore")
                    if dec.startswith("http"):
                        return dec
            except Exception:
                pass
            return url

        soup = BeautifulSoup(html, "lxml")
        results = []
        for li in soup.select("li.b_algo"):
            a = li.select_one("h2 a")
            if not a or not a.get("href"):
                continue
            href = resolve_bing(a["href"])
            if not is_safe_url(href):
                continue
            snippet_el = li.select_one("p")
            results.append(SearchResult(
                title=a.get_text(" ", strip=True),
                url=href,
                snippet=snippet_el.get_text(" ", strip=True) if snippet_el else "",
                provider=self.name,
                kind="text",
            ))
            if len(results) >= limit:
                break
        # Keep only results tied to distinctive query terms; drop generic noise.
        return [r for r in results if has_query_match(query, r.title + " " + r.url + " " + r.snippet)]


class BingImagesProvider(BaseProvider):
    name = "bing_images"

    def available(self) -> bool:
        return True

    async def search(self, query: str, kind: str = "image", limit: int = 20) -> List[SearchResult]:
        if kind != "image":
            return []
        target = (
            "https://www.bing.com/images/async?q=" + quote_plus(query)
            + "&first=1&count=35&mmasync=1&mkt=pt-BR&setlang=pt-BR&cc=br"
        )
        if not is_safe_url(target):
            return []
        html = ""
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = await client.get(target)
                resp.raise_for_status()
                html = resp.text
        except Exception:
            html = ""
        if not html or ("iusc" not in html and '"murl"' not in html):
            try:
                async with httpx.AsyncClient(
                    timeout=settings.request_timeout,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html", "X-Return-Format": "html"},
                ) as client:
                    resp = await client.get("https://r.jina.ai/" + target)
                    resp.raise_for_status()
                    html = resp.text
            except Exception:
                html = ""
        if not html:
            return []
        from bs4 import BeautifulSoup
        import json

        soup = BeautifulSoup(html, "lxml")
        results: List[SearchResult] = []
        seen: set[str] = set()
        for a in soup.select("a.iusc"):
            try:
                meta = json.loads(a.get("m") or "{}")
            except Exception:
                continue
            url = meta.get("murl") or meta.get("imgurl")
            if not url or not is_safe_url(url) or url in seen:
                continue
            seen.add(url)
            title = meta.get("t") or meta.get("desc") or query
            thumb = meta.get("turl") or meta.get("thumbnail") or url
            results.append(SearchResult(
                title=str(title),
                url=url,
                snippet=str(meta.get("desc") or ""),
                provider=self.name,
                thumbnail=thumb,
                kind="image",
            ))
            if len(results) >= limit:
                break
        if not results:
            for m in re.finditer(r'"murl":"(https?://[^"]+)"', html):
                url = m.group(1).replace("\\/", "/")
                if not is_safe_url(url) or url in seen:
                    continue
                seen.add(url)
                results.append(SearchResult(title=query, url=url, snippet="", provider=self.name, thumbnail=url, kind="image"))
                if len(results) >= limit:
                    break
        return results


class DuckDuckGoImagesProvider(BaseProvider):
    name = "duckduckgo_images"

    def available(self) -> bool:
        return True

    async def search(self, query: str, kind: str = "image", limit: int = 20) -> List[SearchResult]:
        if kind != "image":
            return []
        page_url = "https://duckduckgo.com/?q=" + quote_plus(query) + "&iax=images&ia=images"
        if not is_safe_url(page_url):
            return []
        vqd = ""
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = await client.get(page_url)
                resp.raise_for_status()
                m = re.search(r"vqd=([0-9-]+)", resp.text)
                if m:
                    vqd = m.group(1)
        except Exception:
            vqd = ""
        if not vqd:
            try:
                async with httpx.AsyncClient(
                    timeout=settings.request_timeout,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html", "X-Return-Format": "html"},
                ) as client:
                    resp = await client.get("https://r.jina.ai/" + page_url)
                    resp.raise_for_status()
                    m = re.search(r"vqd=([0-9-]+)", resp.text)
                    if m:
                        vqd = m.group(1)
            except Exception:
                vqd = ""
        if not vqd:
            return []
        api_url = (
            "https://duckduckgo.com/i.js?l=pt-br&o=json&q=" + quote_plus(query)
            + "&vqd=" + vqd + "&f=,,,size:Medium"
        )
        if not is_safe_url(api_url):
            return []
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://duckduckgo.com/"}) as client:
                resp = await client.get(api_url)
                resp.raise_for_status()
                data = json.loads(resp.text)
        except Exception:
            return []
        results: List[SearchResult] = []
        seen: set[str] = set()
        for item in data.get("results", []):
            url = item.get("image")
            if not url or not is_safe_url(url) or url in seen:
                continue
            seen.add(url)
            results.append(SearchResult(
                title=str(item.get("title") or query),
                url=url,
                snippet=str(item.get("source") or ""),
                provider=self.name,
                thumbnail=item.get("thumbnail") or url,
                kind="image",
            ))
            if len(results) >= limit:
                break
        return results


class WikipediaProvider(BaseProvider):
    name = "wikipedia"

    def available(self) -> bool:
        return True

    async def search(self, query: str, kind: str = "text", limit: int = 8) -> List[SearchResult]:
        if kind == "image":
            return []
        results: List[SearchResult] = []
        for lang in ("pt", "en"):
            url = f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={quote_plus(query)}&limit={limit}&namespace=0&format=json"
            if not is_safe_url(url):
                continue
            try:
                async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
            except Exception:
                continue
            if not isinstance(data, list) or len(data) < 4:
                continue
            titles = data[1]
            descriptions = data[2]
            urls = data[3]
            for t, d, u in zip(titles, descriptions, urls):
                if not is_safe_url(u):
                    continue
                results.append(SearchResult(title=t, url=u, snippet=d or "", provider=f"wikipedia_{lang}", kind="text"))
        # dedup by url
        seen = set()
        unique = []
        for r in results:
            if r.url in seen:
                continue
            seen.add(r.url)
            unique.append(r)
        return unique[:limit]


class WikimediaCommonsProvider(BaseProvider):
    name = "wikimedia_commons"

    def available(self) -> bool:
        return True

    async def search(self, query: str, kind: str = "image", limit: int = 20) -> List[SearchResult]:
        if kind != "image":
            return []
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urlencode(params)
        if not is_safe_url(url):
            return []
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []
        pages = (data.get("query") or {}).get("pages") or {}
        results = []
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            img_url = info.get("url")
            if not img_url or not is_safe_url(img_url):
                continue
            title = page.get("title", "").replace("File:", "")
            ext = info.get("extmetadata") or {}
            desc = (ext.get("ImageDescription") or {}).get("value", "")
            # strip html
            desc = re.sub(r"<[^>]+>", " ", desc)
            results.append(SearchResult(
                title=title,
                url=img_url,
                snippet=desc[:300],
                provider=self.name,
                thumbnail=info.get("thumburl") or img_url,
                kind="image",
            ))
        return results[:limit]


class OpenverseProvider(BaseProvider):
    name = "openverse"

    def available(self) -> bool:
        return True

    async def search(self, query: str, kind: str = "image", limit: int = 20) -> List[SearchResult]:
        if kind != "image":
            return []
        url = "https://api.openverse.org/v1/images/?q=" + quote_plus(query) + f"&page_size={limit}"
        if not is_safe_url(url):
            return []
        fetch_url = url
        if settings.search_proxy_url:
            fetch_url = settings.search_proxy_url + "?url=" + quote_plus(url)
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, headers={"User-Agent": "ResearchAI/1.0 (contact@example.com)"}) as client:
                resp = await client.get(fetch_url)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []
        results = []
        for item in data.get("results", [])[:limit]:
            img_url = item.get("url")
            if not img_url or not is_safe_url(img_url):
                continue
            results.append(SearchResult(
                title=item.get("title") or img_url,
                url=img_url,
                snippet=item.get("description") or "",
                provider=self.name,
                thumbnail=item.get("thumbnail") or img_url,
                kind="image",
            ))
        return results


def default_providers() -> List[BaseProvider]:
    providers: List[BaseProvider] = []
    if settings.searxng_url:
        providers.append(SearXNGProvider())
    providers.append(BingHTMLProvider())
    providers.append(BingImagesProvider())
    providers.append(DuckDuckGoImagesProvider())
    providers.append(DuckDuckGoHTMLProvider())
    providers.append(WikipediaProvider())
    providers.append(WikimediaCommonsProvider())
    providers.append(OpenverseProvider())
    return providers