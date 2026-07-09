"""Bocha AI web search adapter."""
from __future__ import annotations

from typing import Any

import httpx


class BochaSearchTool:
    """Small LangChain-style adapter with an invoke() method."""

    def __init__(
        self,
        api_key: str,
        api_url: str = "https://api.bocha.cn/v1/web-search",
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.timeout = timeout

    def invoke(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        payload = {
            "query": query,
            "freshness": kwargs.get("freshness", "noLimit"),
            "summary": kwargs.get("summary", True),
            "count": kwargs.get("count", 5),
        }
        if kwargs.get("include"):
            payload["include"] = kwargs["include"]
        if kwargs.get("exclude"):
            payload["exclude"] = kwargs["exclude"]

        response = httpx.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._normalize(response.json())

    def _normalize(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        pages = data.get("webPages") or {}
        values = pages.get("value") or []
        results = []
        for item in values:
            results.append(
                {
                    "title": item.get("name") or item.get("displayUrl") or "web_search",
                    "url": item.get("url"),
                    "content": item.get("summary") or item.get("snippet") or "",
                    "site_name": item.get("siteName"),
                    "date_published": item.get("datePublished") or item.get("dateLastCrawled"),
                }
            )
        return results
