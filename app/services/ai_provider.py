"""Thin abstraction over an OpenAI-compatible chat API."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings


class AIProvider:
    def __init__(self) -> None:
        self.api_key = settings.ai_api_key
        self.base_url = settings.ai_base_url
        self.model = settings.ai_model
        self.timeout = settings.ai_timeout

    def available(self) -> bool:
        return bool(self.api_key and self.model)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        response_format_json: bool = False,
    ) -> Optional[str]:
        if not self.available():
            return None
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or settings.ai_max_tokens,
        }
        if response_format_json:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            return None

    async def chat_json(self, messages: List[Dict[str, str]], **kwargs: Any) -> Optional[Dict[str, Any]]:
        text = await self.chat(messages, response_format_json=True, **kwargs)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON object
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
        return None


ai_provider = AIProvider()