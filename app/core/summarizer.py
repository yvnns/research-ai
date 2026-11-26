"""Summarize research results."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.ai_provider import ai_provider


def _fallback_summary(query: str, facts: List[Dict], images: List[Dict], reliability: Dict) -> str:
    lines = [f"Pesquisa: {query}", ""]
    lines.append(f"Foram encontradas {len(images)} imagens e {len(facts)} informações extraídas de {reliability.get('sources_count', 0)} fontes.")
    # Group facts by key
    grouped: Dict[str, List[str]] = {}
    for f in facts:
        grouped.setdefault(f.get("key", "Informação"), []).append(f.get("value", ""))
    for key, vals in list(grouped.items())[:8]:
        lines.append(f"- {key}: " + " / ".join(v[:120] for v in vals[:2]))
    if reliability.get("missing"):
        lines.append("Pontos a verificar: " + ", ".join(reliability["missing"]) + ".")
    return "\n".join(lines)


async def summarize(query: str, facts: List[Dict], images: List[Dict], sources: List[Dict], reliability: Dict, plan: Dict) -> str:
    if ai_provider.available():
        fact_text = "\n".join(f"- {f.get('key')}: {str(f.get('value'))[:240]}" for f in facts[:25])
        img_text = f"{len(images)} imagens (confirmadas/similares: {sum(1 for i in images if i.get('verification_status') in ('likely_match','similar'))})"
        prompt = (
            "Resuma a pesquisa de forma clara e objetiva em português do Brasil. "
            "Não invente informações. Use apenas os dados fornecidos. "
            f"Consulta: {query}\n"
            f"Plano: {plan.get('intent')}\n"
            f"Imagens: {img_text}\n"
            f"Informações:\n{fact_text}\n"
            "Estruture em: resumo, características principais, informações técnicas, complementares e confiabilidade."
        )
        result = await ai_provider.chat(
            [{"role": "system", "content": "Você é um assistente de pesquisa factual."}, {"role": "user", "content": prompt}],
            temperature=0.2,
        )
        if result:
            return result.strip()
    return _fallback_summary(query, facts, images, reliability)