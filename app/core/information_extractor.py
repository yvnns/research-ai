"""Extract structured and unstructured information from collected pages."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.core.relevance import distinctive_tokens, has_query_match
from app.database import db


def _chunks(text: str, max_len: int = 280) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    out = []
    for s in sentences:
        s = s.strip()
        if len(s) < 40:
            continue
        if len(s) > max_len:
            s = s[:max_len].rsplit(" ", 1)[0] + "..."
        out.append(s)
    return out


def _extract_tables(page: Dict, source_id: Optional[str]) -> List[Dict[str, Any]]:
    facts = []
    q = page.get("_query") or ""
    for table in page.get("tables", []):
        for row in table:
            if len(row) >= 2:
                key = row[0].strip()
                value = " | ".join(c.strip() for c in row[1:] if c.strip())
                if not key or not value or len(key) >= 80:
                    continue
                if q and not has_query_match(q, key + " " + value):
                    continue
                facts.append({"key": key, "value": value, "source_id": source_id, "confidence": "secondary"})
    return facts


def _extract_meta(page: Dict, source_id: Optional[str]) -> List[Dict[str, Any]]:
    facts = []
    title = page.get("title")
    if title:
        facts.append({"key": "Título da página", "value": title, "source_id": source_id, "confidence": "secondary"})
    # meta description not stored separately; include first chunk as description
    text = page.get("text", "")
    if text:
        facts.append({"key": "Descrição encontrada", "value": text[:400], "source_id": source_id, "confidence": "secondary"})
    return facts


def _keyword_facts(text: str, query: str, source_id: Optional[str]) -> List[Dict[str, Any]]:
    q_tokens = distinctive_tokens(query)
    facts = []
    for sentence in _chunks(text):
        low = sentence.lower()
        if any(t in low for t in q_tokens) or any(k in low for k in ("medida", "mola", "material", "garantia", "peso", "dimens")):
            facts.append({"key": "Informação relevante", "value": sentence, "source_id": source_id, "confidence": "secondary"})
    # Limit per page
    return facts[:8]


async def extract_from_page(search_id: str, page: Dict, source_id: Optional[str]) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    facts.extend(_extract_tables(page, source_id))
    facts.extend(_extract_meta(page, source_id))
    facts.extend(_keyword_facts(page.get("text", ""), page.get("_query", ""), source_id))

    # Persist
    stored = []
    for f in facts:
        # Avoid exact duplicate values already stored for this search
        fid = await db.insert_fact(search_id, f["key"], f["value"], f.get("source_id"), f.get("confidence", "inferred"), "unverified")
        item = dict(f)
        item["id"] = fid
        stored.append(item)
    return stored


async def extract_pdf_facts(search_id: str, pdf_result: Dict, source_id: Optional[str], query: str) -> List[Dict[str, Any]]:
    text = pdf_result.get("text", "")
    if not text:
        return []
    facts = []
    for sentence in _chunks(text, 320):
        facts.append({"key": "Informação de documento", "value": sentence, "source_id": source_id, "confidence": "secondary"})
    # tables not extracted from PDF here
    stored = []
    for f in facts[:20]:
        fid = await db.insert_fact(search_id, f["key"], f["value"], f.get("source_id"), f.get("confidence", "inferred"), "unverified")
        item = dict(f)
        item["id"] = fid
        stored.append(item)
    return stored