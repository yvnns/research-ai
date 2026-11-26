"""Image analysis, hashing and relevance scoring."""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

from app.config import settings


def _tokens(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-zA-Z0-9À-ÿ]+", (text or "").lower()) if len(t) > 2]


def compute_phash(image_bytes: bytes, hash_size: int = 8) -> Optional[str]:
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
            pixels = list(img.getdata())
        bits = []
        for row in range(hash_size):
            for col in range(hash_size):
                idx = row * (hash_size + 1) + col
                bits.append(1 if pixels[idx] < pixels[idx + 1] else 0)
        # pack bits into hex
        value = 0
        for bit in bits:
            value = (value << 1) | bit
        return format(value, "016x")
    except Exception:
        return None


def hamming_distance(a: Optional[str], b: Optional[str]) -> int:
    if not a or not b or len(a) != len(b):
        return 64
    try:
        x = int(a, 16) ^ int(b, 16)
        return bin(x).count("1")
    except ValueError:
        return 64


def is_near_duplicate(phash: Optional[str], existing: List[str], threshold: Optional[int] = None) -> bool:
    threshold = threshold if threshold is not None else settings.phash_distance_threshold
    if not phash:
        return False
    for other in existing:
        if hamming_distance(phash, other) <= threshold:
            return True
    return False


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def score_image(query: str, url: str, alt: str = "", page_title: str = "", context: str = "", width: Optional[int] = None, height: Optional[int] = None) -> float:
    q_tokens = _tokens(query)
    if not q_tokens:
        return 0.1
    haystack = " ".join([url, alt, page_title, context]).lower()
    matches = sum(1 for t in q_tokens if t in haystack)
    base = matches / len(q_tokens)
    # dimension boost
    if width and height and width >= 200 and height >= 200:
        base += 0.1
    # penalties for icons/logos
    low_url = url.lower()
    if any(k in low_url for k in ("logo", "icon", "favicon", "sprite", "banner")):
        base -= 0.25
    # boost common image extensions
    if any(low_url.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
        base += 0.05
    return max(0.0, min(1.0, base))


def classify_image(score: float, url: str, alt: str = "") -> str:
    low = (url + " " + alt).lower()
    if any(k in low for k in ("diagram", "diagrama", "esquema", "medida", "dimension")):
        return "technical"
    if score >= 0.75:
        return "confirmed"
    if score >= 0.45:
        return "similar"
    if any(k in low for k in ("catalog", "catalogo", "loja", "store", "shop")):
        return "commercial"
    return "illustration"