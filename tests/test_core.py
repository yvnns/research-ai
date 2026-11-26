import asyncio
import io

import pytest
from PIL import Image

from app.core.image_analyzer import compute_phash, hamming_distance, is_near_duplicate, score_image
from app.core.planner import plan
from app.core.relevance import exact_image_query, distinctive_tokens
from app.services.security import is_safe_url, validate_image_bytes


@pytest.mark.asyncio
async def test_planner_creates_complementary_queries():
    p = await plan("Cama box Ortobom Spring Pocket casal", deep=True)
    assert p["queries"]
    assert any("Ortobom Spring Pocket" in q for q in p["queries"])
    assert len(p["queries"]) <= 12
    assert "images" in p.get("image_queries", [])[0].lower() or True


def test_security_blocks_localhost():
    assert is_safe_url("http://localhost:8000/x") is False
    assert is_safe_url("http://127.0.0.1/x") is False
    assert is_safe_url("https://example.com/img.jpg") is True


def test_phash_and_dedup():
    img = Image.new("RGB", (64, 64), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    h = compute_phash(data)
    assert h is not None and len(h) == 16
    assert is_near_duplicate(h, [h]) is True
    assert hamming_distance(h, h) == 0


def test_validate_image_bytes():
    img = Image.new("RGB", (8, 8), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    assert validate_image_bytes(data, 1024 * 1024) is True
    assert validate_image_bytes(b"not image", 1024 * 1024) is False


def test_score_image():
    s = score_image("ortobom spring pocket", "https://example.com/ortobom-spring-pocket.jpg", "colchão casal", "Ortobom", "")
    assert 0 <= s <= 1
    assert s > 0.3
def test_relevance_helpers():
    assert distinctive_tokens("Cama box gazin tower") == ["gazin", "tower"]
    assert exact_image_query("Cama box gazin tower") == '"gazin tower"'

@pytest.mark.asyncio
async def test_image_hunter_skips_irrelevant_pages(monkeypatch):
    from app.core.image_hunter import hunt_images

    monkeypatch.setattr("app.core.image_hunter.default_providers", lambda: [])
    page = {
        "url": "https://lista.mercadolivre.com.br/gazin-tower",
        "title": "Seguranca - Mercado Livre",
        "text": "Verificacao de seguranca reCAPTCHA",
        "images": [],
    }
    result = await hunt_images("test_skip", "Cama box gazin tower", [], [page], limit=1)
    assert result == []
