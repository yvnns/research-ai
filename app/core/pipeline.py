"""Orchestrates a full research run."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any, Dict, List, Optional

from app.config import settings
from app.core.information_extractor import extract_from_page, extract_pdf_facts
from app.core.image_hunter import hunt_images
from app.core.planner import plan
from app.core.summarizer import summarize
from app.core.verifier import verify_search
from app.core.web_collector import collect_pages, fetch_page, extract_links_for_deepening
from app.database import db
from app.models.schemas import SearchResponse, ImageMeta, Fact, SourceRef
from app.services.search_providers import default_providers
from app.services.security import is_safe_url


def _cache_key(query: str, deep: bool) -> str:
    return hashlib.sha256(f"{query.strip().lower()}|deep={deep}".encode()).hexdigest()


async def run_search(search_id: str, refresh: bool = False) -> None:
    start = time.time()
    try:
        search = await db.get_search(search_id)
        if not search:
            return
        query = search["query"]
        deep = bool(search["deep"])
        max_images = search["max_images"] or settings.max_images
        max_pages = search["max_pages"] or settings.max_pages
        max_cycles = settings.max_cycles if deep else 1

        # Cache check
        if settings.reuse_cache and not refresh:
            cached = await db.cache_get(_cache_key(query, deep))
            if cached:
                await db.update_search(
                    search_id,
                    status="completed",
                    stage="Finalizado",
                    progress=100,
                    message="Resultado reutilizado do cache.",
                    summary=cached.get("summary"),
                    result_json=json.dumps(cached, ensure_ascii=False),
                    reliability_json=json.dumps(cached.get("reliability", {}), ensure_ascii=False),
                )
                return

        await db.update_search(search_id, status="running", stage="Planejando", progress=5, message="Interpretando a consulta e criando plano de pesquisa.")

        research_plan = await plan(query, deep)
        await db.update_search(search_id, plan_json=json.dumps(research_plan, ensure_ascii=False), progress=10, message="Plano de pesquisa criado.")

        providers = default_providers()
        executed_queries: set[str] = set()
        collected_pages: List[Dict] = []
        collected_urls: set[str] = set()
        source_url_to_id: Dict[str, str] = {}

        async def run_text_search(q: str, cycle: int) -> List[str]:
            nonlocal collected_pages
            urls: List[str] = []
            tasks = []
            for p in providers:
                if not p.available():
                    continue
                # text providers only
                if p.name in ("wikimedia_commons", "openverse"):
                    continue
                tasks.append(p.search(q, kind="text", limit=8))
            for res in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(res, Exception) or not res:
                    continue
                generic_tokens = {"cama", "box", "colchao", "colchão", "sofa", "sofá", "mesa", "cadeira", "produto", "modelos"}
                distinctive_tokens = [t for t in re.findall(r"\\w{3,}", query.lower()) if t not in generic_tokens]
                for r in res:
                    if r.url in collected_urls:
                        continue
                    if distinctive_tokens and not any(tok in (r.title + " " + r.url + " " + r.snippet).lower() for tok in distinctive_tokens):
                        continue
                    collected_urls.add(r.url)
                    # insert source
                    src_id = await db.insert_source(search_id, r.url, r.title, r.snippet, r.provider, "secondary")
                    source_url_to_id[r.url] = src_id
                    urls.append(r.url)
            return urls

        all_urls_to_collect: List[str] = []

        for cycle in range(max_cycles):
            if time.time() - start > settings.max_search_seconds:
                break
            progress = 15 + int((cycle / max(max_cycles, 1)) * 40)
            await db.update_search(search_id, stage="Pesquisando", progress=progress, message=f"Ciclo de pesquisa {cycle + 1}/{max_cycles}.")

            # Determine queries for this cycle
            cycle_queries = []
            for q in research_plan.get("queries", []) + research_plan.get("image_queries", []):
                if q not in executed_queries:
                    cycle_queries.append(q)
            # Add gap-based queries
            if cycle > 0 and len(collected_pages) < 5:
                for suffix in ("fotos", "detalhes", "especificações"):
                    sq = f"{query} {suffix}"
                    if sq not in executed_queries:
                        cycle_queries.append(sq)
            cycle_queries = cycle_queries[: max(1, settings.max_queries // max_cycles)]

            for q in cycle_queries:
                if q in executed_queries:
                    continue
                if time.time() - start > settings.max_search_seconds:
                    break
                executed_queries.add(q)
                await db.insert_query(search_id, q, "planner", cycle)
                urls = await run_text_search(q, cycle)
                all_urls_to_collect.extend(urls)

            # Collect pages up to max_pages
            await db.update_search(search_id, stage="Coletando", progress=min(progress + 5, 55), message="Coletando e extraindo conteúdo das páginas.")
            remaining = max_pages - len(collected_pages)
            if remaining > 0:
                batch = [u for u in all_urls_to_collect if u not in {p["url"] for p in collected_pages}][:remaining]
                pages = await collect_pages(batch, limit=remaining)
                for p in pages:
                    p["_query"] = query
                    collected_pages.append(p)
                    # Extract facts
                    src_id = source_url_to_id.get(p["url"])
                    await extract_from_page(search_id, p, src_id)
                    # PDF handling
                    if p.get("is_pdf"):
                        raw = p.get("raw")
                        if raw:
                            from app.core.document_parser import parse_pdf_bytes

                            parsed = parse_pdf_bytes(raw)
                            await extract_pdf_facts(search_id, parsed, src_id, query)

            # Deepen: follow promising links to reach product pages with higher-quality images.
            if len(collected_pages) < max_pages:
                deep_links = []
                for p in collected_pages:
                    deep_links.extend(extract_links_for_deepening(p, [query] + research_plan.get("queries", []), limit=2))
                new_links = []
                collected_url_set = {p["url"] for p in collected_pages}
                for link in deep_links:
                    if link in collected_url_set or link in collected_urls:
                        continue
                    collected_urls.add(link)
                    new_links.append(link)
                    all_urls_to_collect.append(link)
                if new_links:
                    remaining = max_pages - len(collected_pages)
                    batch = new_links[:remaining]
                    pages = await collect_pages(batch, limit=remaining)
                    for p in pages:
                        p["_query"] = query
                        collected_pages.append(p)
                        src_id = source_url_to_id.get(p["url"])
                        # register source if missing
                        if p["url"] not in source_url_to_id:
                            sid_src = await db.insert_source(search_id, p["url"], p.get("title"), "", "deep_link", "secondary")
                            source_url_to_id[p["url"]] = sid_src
                        await extract_from_page(search_id, p, source_url_to_id.get(p["url"]))

        # Image hunting
        await db.update_search(search_id, stage="Analisando imagens", progress=65, message="Buscando e validando imagens.")
        images = await hunt_images(
            search_id=search_id,
            query=query,
            image_queries=research_plan.get("image_queries", []),
            collected_pages=collected_pages,
            limit=max_images,
        )

        # Verification
        await db.update_search(search_id, stage="Verificando informações", progress=80, message="Verificando fontes e consistência.")
        reliability = await verify_search(search_id)

        # Summarize
        await db.update_search(search_id, stage="Finalizando", progress=90, message="Gerando resumo.")
        facts = await db.list_facts(search_id)
        sources = await db.list_sources(search_id)
        images_db = await db.list_images(search_id)
        summary = await summarize(query, facts, images_db, sources, reliability, research_plan)

        # Build response payload
        image_metas = []
        for im in images_db:
            image_metas.append({
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
            })
        fact_list = [
            {
                "id": f["id"],
                "key": f["key"],
                "value": f["value"],
                "source_id": f["source_id"],
                "confidence": f["confidence"],
                "status": f["status"],
            }
            for f in facts
        ]
        source_list = [
            {
                "id": s["id"],
                "url": s["url"],
                "title": s["title"],
                "snippet": s["snippet"],
                "provider": s["provider"],
                "confidence": s["confidence"],
            }
            for s in sources
        ]

        payload = {
            "id": search_id,
            "query": query,
            "status": "completed",
            "stage": "Finalizado",
            "progress": 100,
            "message": "Pesquisa concluída.",
            "summary": summary,
            "images": image_metas,
            "facts": fact_list,
            "sources": source_list,
            "plan": research_plan,
            "reliability": reliability,
        }

        await db.update_search(
            search_id,
            status="completed",
            stage="Finalizado",
            progress=100,
            message="Pesquisa concluída.",
            summary=summary,
            result_json=json.dumps(payload, ensure_ascii=False),
            reliability_json=json.dumps(reliability, ensure_ascii=False),
        )

        # Cache store
        if settings.reuse_cache:
            await db.cache_set(_cache_key(query, deep), payload, settings.cache_ttl_hours)

    except Exception as exc:
        await db.update_search(search_id, status="failed", stage="Erro", progress=100, message="Falha na pesquisa.", error=str(exc))