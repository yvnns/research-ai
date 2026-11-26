"""Research planner: turns a user question into complementary queries."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.services.ai_provider import ai_provider

PRODUCT_HINTS = {
    "cama", "colchão", "colchao", "sofá", "sofa", "geladeira", "fogão", "fogao",
    "máquina", "maquina", "armário", "armario", "mesa", "cadeira", "produto",
    "modelo", "eletrodoméstico", "eletrodomestico",
}

GENERAL_TARGET_FIELDS = [
    "resumo", "descrição", "características", "contexto", "fontes", "imagens relevantes"
]

PRODUCT_TARGET_FIELDS = [
    "marca", "modelo", "categoria", "medidas", "material", "características",
    "especificações técnicas", "tipo de funcionamento", "garantia", "imagens",
]


def _clean(q: str) -> str:
    return re.sub(r"\s+", " ", q).strip()


def _heuristic_plan(query: str, deep: bool) -> Dict[str, Any]:
    q = _clean(query)
    low = q.lower()
    is_product = any(h in low for h in PRODUCT_HINTS) or any(ch.isdigit() for ch in q)
    needs_images = True
    needs_docs = deep
    needs_text = True

    fields = PRODUCT_TARGET_FIELDS if is_product else GENERAL_TARGET_FIELDS

    queries = [q]
    # Complementary, non-repetitive variants
    variants = [
        f"{q} ficha técnica",
        f"{q} especificações",
        f"{q} medidas",
        f"{q} catálogo PDF",
        f"{q} imagens produto",
        f"{q} site oficial",
        f"{q} wikipedia",
    ]
    if not is_product:
        variants = [
            f"{q}",
            f"{q} explicação",
            f"{q} características",
            f"{q} imagens",
            f"{q} wikipedia",
            f"{q} pesquisa técnica",
        ]
    for v in variants:
        if v not in queries:
            queries.append(v)

    image_queries = [f"{q} imagens", f"{q} foto real", f"{q} catálogo"]
    doc_queries = [f"{q} ficha técnica PDF", f"{q} manual PDF"] if deep else []

    # Limit
    from app.config import settings

    queries = queries[: settings.max_queries]
    return {
        "subject": q,
        "intent": "product_research" if is_product else "general_research",
        "needs": {"images": needs_images, "text": needs_text, "documents": needs_docs},
        "target_fields": fields,
        "queries": queries,
        "image_queries": image_queries,
        "doc_queries": doc_queries,
    }


async def plan(query: str, deep: bool = True) -> Dict[str, Any]:
    base = _heuristic_plan(query, deep)
    if not ai_provider.available():
        return base

    prompt = (
        "Você é um planejador de pesquisa. Dada a consulta do usuário, retorne JSON com: "
        "subject, intent, needs (images,text,documents booleans), target_fields (lista), "
        "queries (lista de consultas complementares), image_queries (lista), doc_queries (lista). "
        "Não invente fatos. Apenas planeje buscas. Consulta: " + query
    )
    data = await ai_provider.chat_json(
        [{"role": "system", "content": "Responda apenas JSON válido."}, {"role": "user", "content": prompt}],
        temperature=0.1,
    )
    if not data or not isinstance(data.get("queries"), list):
        return base

    # Merge AI output with safe fallback
    merged = dict(base)
    for key in ("subject", "intent"):
        if isinstance(data.get(key), str) and data[key].strip():
            merged[key] = data[key].strip()
    if isinstance(data.get("needs"), dict):
        for k in ("images", "text", "documents"):
            if k in data["needs"]:
                merged["needs"][k] = bool(data["needs"][k])
    if isinstance(data.get("target_fields"), list):
        merged["target_fields"] = [str(x) for x in data["target_fields"] if x][:20]
    if isinstance(data.get("queries"), list):
        qs = [_clean(str(x)) for x in data["queries"] if str(x).strip()]
        # ensure original query included
        if query not in qs:
            qs.insert(0, query)
        # dedup
        seen = set()
        uniq = []
        for q in qs:
            if q.lower() in seen:
                continue
            seen.add(q.lower())
            uniq.append(q)
        from app.config import settings

        merged["queries"] = uniq[: settings.max_queries]
    if isinstance(data.get("image_queries"), list):
        merged["image_queries"] = [_clean(str(x)) for x in data["image_queries"] if str(x).strip()][:10]
    if isinstance(data.get("doc_queries"), list):
        merged["doc_queries"] = [_clean(str(x)) for x in data["doc_queries"] if str(x).strip()][:10]
    return merged