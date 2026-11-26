"""Shared query relevance helpers."""

from __future__ import annotations

import re
from typing import List

_GENERIC_TOKENS = {
    "cama", "box", "colchao", "colchão", "sofá", "sofa", "mesa", "cadeira",
    "produto", "produtos", "modelos", "preco", "preço", "comprar", "melhor",
    "mercado", "imagens", "imagem", "fotos", "foto", "explicacao", "explicação",
    "caracteristicas", "características", "especificacoes", "especificações",
    "medidas", "catalogo", "catálogo", "site", "wikipedia", "ficha", "tecnica",
    "técnica", "pdf", "real", "detalhes", "ofertas", "oferta",
}


def query_tokens(query: str) -> List[str]:
    return [t for t in re.findall(r"\w+", (query or "").lower()) if len(t) >= 2]


def distinctive_tokens(query: str) -> List[str]:
    tokens = query_tokens(query)
    distinctive = [t for t in tokens if t not in _GENERIC_TOKENS]
    return distinctive or tokens


def has_query_match(query: str, text: str) -> bool:
    low = (text or "").lower()
    return any(tok in low for tok in distinctive_tokens(query))


def exact_image_query(query: str) -> str:
    return '"' + " ".join(distinctive_tokens(query)[:3]) + '"'
