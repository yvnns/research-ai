"""URL and file safety helpers."""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from app.config import settings


BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def is_safe_url(url: str, allow_private: Optional[bool] = None) -> bool:
    if allow_private is None:
        allow_private = settings.allow_private_networks
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in BLOCKED_HOSTS:
        return False
    # Block obvious private hostnames
    if host.endswith(".local") or host.endswith(".internal"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        # DNS resolution failure is not necessarily unsafe; caller will fail later.
        return True
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local:
            return False
        if not allow_private and (addr.is_private or addr.is_reserved or addr.is_multicast):
            return False
    return True


def safe_filename(name: str, default: str = "file") -> str:
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    cleaned = cleaned.strip("._")
    if not cleaned:
        cleaned = default
    return cleaned[:120]


def validate_image_bytes(data: bytes, max_bytes: int) -> bool:
    if not data or len(data) > max_bytes:
        return False
    # Magic bytes for common image formats
    signatures = {
        b"\xff\xd8\xff": "jpeg",
        b"\x89PNG\r\n\x1a\n": "png",
        b"GIF87a": "gif",
        b"GIF89a": "gif",
        b"RIFF": "webp",  # further check
        b"BM": "bmp",
    }
    for sig in signatures:
        if data.startswith(sig):
            if sig == b"RIFF":
                return len(data) > 12 and data[8:12] == b"WEBP"
            return True
    return False


def ensure_within(base: Path, target: Path) -> bool:
    try:
        base_resolved = base.resolve()
        target_resolved = target.resolve()
        return str(target_resolved).startswith(str(base_resolved) + "/") or target_resolved == base_resolved
    except Exception:
        return False