"""Pydantic models shared by the API and core modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, HttpUrl


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    deep: bool = True
    max_images: Optional[int] = None
    max_pages: Optional[int] = None
    refresh: bool = False


class SearchResultRef(BaseModel):
    id: str
    query: str
    status: str
    created_at: datetime
    updated_at: datetime


class SourceRef(BaseModel):
    id: str
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    provider: Optional[str] = None
    confidence: str = "secondary"


class ImageMeta(BaseModel):
    id: str
    url: str
    page_url: Optional[str] = None
    local_url: str
    thumb_url: Optional[str] = None
    filename: str
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    size: Optional[int] = None
    relevance: float = 0.0
    classification: str = "unknown"  # confirmed, similar, technical, commercial, illustration
    verification_status: str = "unverified"
    is_duplicate: bool = False
    source_id: Optional[str] = None


class Fact(BaseModel):
    id: str
    key: str
    value: str
    source_id: Optional[str] = None
    confidence: str = "inferred"  # confirmed, secondary, inferred, contradictory, not_found
    status: str = "unverified"


class SearchStatus(BaseModel):
    id: str
    query: str
    status: str
    stage: str
    progress: int
    message: str
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None


class SearchResponse(BaseModel):
    id: str
    query: str
    status: str
    stage: str
    progress: int
    message: str
    summary: Optional[str] = None
    images: List[ImageMeta] = []
    facts: List[Fact] = []
    sources: List[SourceRef] = []
    plan: Dict[str, Any] = {}
    reliability: Dict[str, Any] = {}
    error: Optional[str] = None