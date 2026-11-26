"""Verification and reliability assessment."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List
from urllib.parse import urlparse

from app.database import db


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


async def verify_search(search_id: str) -> Dict[str, Any]:
    facts = await db.list_facts(search_id)
    sources = await db.list_sources(search_id)
    source_map = {s["id"]: s for s in sources}
    images = await db.list_images(search_id)

    # Group facts by key
    by_key: Dict[str, List[Dict]] = defaultdict(list)
    for f in facts:
        by_key[f["key"]].append(f)

    confirmed = 0
    secondary = 0
    inferred = 0
    contradictory = 0
    not_found = 0

    for key, group in by_key.items():
        # distinct normalized values
        value_groups: Dict[str, List[Dict]] = defaultdict(list)
        for f in group:
            value_groups[_norm(f["value"])].append(f)
        distinct = len(value_groups)
        multi_source_values = 0
        for val, fs in value_groups.items():
            source_ids = {f.get("source_id") for f in fs if f.get("source_id")}
            if len(source_ids) >= 2 or len(fs) >= 2:
                multi_source_values += 1

        for f in group:
            src = source_map.get(f.get("source_id") or "")
            src_url = src["url"] if src else ""
            # Determine confidence
            if distinct > 1 and len(group) > 1:
                # conflicting values for same key
                conf = "contradictory"
            elif multi_source_values > 0:
                conf = "confirmed"
            elif src_url:
                conf = "secondary"
            else:
                conf = "inferred"
            status = "verified" if conf in ("confirmed", "secondary") else "needs_review"
            await db.update_fact(f["id"], confidence=conf, status=status)
            if conf == "confirmed":
                confirmed += 1
            elif conf == "secondary":
                secondary += 1
            elif conf == "contradictory":
                contradictory += 1
            elif conf == "inferred":
                inferred += 1

    # Image verification counts
    img_confirmed = sum(1 for i in images if i.get("verification_status") == "likely_match")
    img_similar = sum(1 for i in images if i.get("verification_status") == "similar")

    # Detect missing info
    missing = []
    if not images:
        missing.append("imagens")
    if not facts:
        missing.append("informações textuais")
    if contradictory > 0:
        missing.append("resolução de divergências")

    reliability = {
        "facts": {
            "confirmed": confirmed,
            "secondary": secondary,
            "inferred": inferred,
            "contradictory": contradictory,
            "not_found": not_found,
        },
        "images": {
            "likely_match": img_confirmed,
            "similar": img_similar,
            "total": len(images),
        },
        "missing": missing,
        "sources_count": len(sources),
    }
    return reliability