"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
STORAGE_DIR = BASE_DIR / "storage"
IMAGES_DIR = STORAGE_DIR / "images"
DOCUMENTS_DIR = STORAGE_DIR / "documents"
CACHE_DIR = STORAGE_DIR / "cache"
DB_PATH = STORAGE_DIR / "research.db"

load_dotenv(BASE_DIR / ".env", override=False)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    app_name: str = os.getenv("APP_NAME", "Research AI")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = _int("PORT", 8000)
    debug: bool = _bool("DEBUG", False)

    # Search limits
    max_queries: int = _int("MAX_QUERIES", 12)
    max_pages: int = _int("MAX_PAGES", 8)
    max_images: int = _int("MAX_IMAGES", 40)
    max_cycles: int = _int("MAX_CYCLES", 2)
    max_search_seconds: int = _int("MAX_SEARCH_SECONDS", 120)
    max_file_size_mb: int = _int("MAX_FILE_SIZE_MB", 15)
    max_download_seconds: int = _int("MAX_DOWNLOAD_SECONDS", 12)
    request_timeout: int = _int("REQUEST_TIMEOUT", 12)
    max_content_length: int = _int("MAX_CONTENT_LENGTH", 2_000_000)

    # Providers
    searxng_url: str = os.getenv("SEARXNG_URL", "").strip()
    search_provider: str = os.getenv("SEARCH_PROVIDER", "auto").strip().lower()

    # AI provider (OpenAI-compatible)
    ai_api_key: str = os.getenv("AI_API_KEY", "").strip()
    ai_base_url: str = os.getenv("AI_BASE_URL", "https://opencode.ai/zen/go/v1").strip().rstrip("/")
    ai_model: str = os.getenv("AI_MODEL", "beam-free").strip()
    ai_vision_model: str = os.getenv("AI_VISION_MODEL", "").strip()
    ai_timeout: int = _int("AI_TIMEOUT", 60)
    ai_max_tokens: int = _int("AI_MAX_TOKENS", 1200)

    # Cache
    cache_ttl_hours: int = _int("CACHE_TTL_HOURS", 24)
    reuse_cache: bool = _bool("REUSE_CACHE", True)

    # Image analysis
    image_relevance_threshold: float = _float("IMAGE_RELEVANCE_THRESHOLD", 0.4)
    phash_distance_threshold: int = _int("PHASH_DISTANCE_THRESHOLD", 8)

    # Security
    allow_private_networks: bool = _bool("ALLOW_PRIVATE_NETWORKS", False)


settings = Settings()

for directory in (STORAGE_DIR, IMAGES_DIR, DOCUMENTS_DIR, CACHE_DIR):
    directory.mkdir(parents=True, exist_ok=True)