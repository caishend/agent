"""浏览器检索、网页截图与截图理解工具。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.agent.tools.base_tool import ArtifactItem, BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult


class BrowserTool(BaseTool):
    name = "browser"
    description = "实时检索互联网信息，打开网页，截取页面，并理解网页截图中的地图、图表和预警信息。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        query = tool_input.query.strip()
        search_query = self._prepare_search_query(query)
        params = tool_input.params or {}
        provided_search_tool = params.get("search_tool")
        search_tool = provided_search_tool or self._default_search_tool()

        if search_tool:
            try:
                raw_results = self._search_with_langchain_tool(search_tool, search_query)
                search_mode = "langchain_search_tool" if provided_search_tool else type(search_tool).__name__
            except Exception as error:
                raw_results = self._offline_fallback_results(search_query, error=str(error))
                search_mode = "offline_fallback"
        else:
            raw_results = self._offline_fallback_results(search_query)
            search_mode = "offline_fallback"

        search_results = self._normalize_search_results(raw_results)
        evidence = self._build_evidence(search_results)
        artifacts, screenshot_observations = self._capture_screenshots_if_needed(
            query=query,
            search_results=search_results,
            params=params,
        )
        confidence = self._estimate_confidence(search_mode, evidence)

        return ToolResult(
            summary=self._build_summary(query, search_results, search_mode, screenshot_observations),
            evidence=evidence,
            artifacts=artifacts,
            confidence=confidence,
            data={
                "search_mode": search_mode,
                "query": search_query,
                "search_results": search_results,
                "screenshot_observations": screenshot_observations,
            },
        )

    def _default_search_tool(self) -> Any | None:
        try:
            from app.agent.tools.adapters.bocha_search import BochaSearchTool
            from app.config import settings
        except ImportError:
            return None
        if not settings.BOCHA_API_KEY:
            return None
        return BochaSearchTool(api_key=settings.BOCHA_API_KEY, api_url=settings.BOCHA_API_URL)

    def _prepare_search_query(self, query: str) -> str:
        cleaned = query.strip()
        for phrase in ("帮我搜索一下", "帮我搜索", "搜索一下", "请搜索", "查一下", "帮我查", "查询"):
            cleaned = cleaned.replace(phrase, " ")
        cleaned = " ".join(cleaned.split())
        if cleaned in {"天气", "天气预报"}:
            cleaned = "当地天气预报"
        return cleaned or query

    def _search_with_langchain_tool(self, search_tool: Any, query: str) -> Any:
        if hasattr(search_tool, "invoke"):
            return search_tool.invoke(query)
        if hasattr(search_tool, "run"):
            return search_tool.run(query)
        if callable(search_tool):
            return search_tool(query)
        return []

    def _offline_fallback_results(self, query: str, error: str | None = None) -> list[dict[str, Any]]:
        content = f"未配置实时搜索工具，暂无法联网检索“{query}”。请接入 Bocha、Tavily、SerpAPI、DuckDuckGo 或 Playwright 搜索后重试。"
        if error:
            content = f"实时搜索调用失败：{error}。已切换为离线提示，无法联网检索“{query}”。"
        return [{"title": "离线检索提示", "url": None, "content": content}]

    def _normalize_search_results(self, raw_results: Any) -> list[dict[str, Any]]:
        if raw_results is None:
            return []
        if isinstance(raw_results, str):
            return [{"title": "web_search", "url": None, "content": raw_results}]
        if isinstance(raw_results, dict):
            raw_items = raw_results["results"] if isinstance(raw_results.get("results"), list) else [raw_results]
        else:
            raw_items = list(raw_results)

        normalized = []
        for item in raw_items:
            if isinstance(item, str):
                normalized.append({"title": "web_search", "url": None, "content": item})
                continue

            title = str(item.get("title") or item.get("source") or item.get("name") or "web_search")
            url = item.get("url") or item.get("link")
            content = str(
                item.get("content")
                or item.get("snippet")
                or item.get("description")
                or item.get("body")
                or ""
            )
            normalized.append(
                {
                    "title": title,
                    "url": url,
                    "content": content,
                    "metadata": {
                        key: value
                        for key, value in item.items()
                        if key
                        not in {
                            "title",
                            "source",
                            "name",
                            "url",
                            "link",
                            "content",
                            "snippet",
                            "description",
                            "body",
                        }
                    },
                }
            )

        return normalized

    def _build_evidence(self, search_results: list[dict[str, Any]]) -> list[EvidenceItem]:
        evidence = []
        for result in search_results:
            evidence.append(
                EvidenceItem(
                    source=result["title"],
                    type="web",
                    content=result["content"],
                    confidence=0.82 if result.get("url") else 0.55,
                    metadata={"url": result.get("url"), **result.get("metadata", {})},
                )
            )
        return evidence

    def _capture_screenshots_if_needed(
        self,
        query: str,
        search_results: list[dict[str, Any]],
        params: dict[str, Any],
    ) -> tuple[list[ArtifactItem], list[str]]:
        wants_screenshot = bool(params.get("capture_screenshot")) or self._query_mentions_screenshot(query)
        screenshotter = params.get("screenshotter") or self._default_screenshotter(wants_screenshot)
        if not screenshotter or not wants_screenshot:
            return [], []

        target_url = self._first_url(search_results)
        if not target_url:
            return [], []

        try:
            screenshot = self._capture_with_adapter(screenshotter, target_url, query)
        except Exception as error:
            return [], [f"网页检索已完成，但截图失败：{type(error).__name__}: {error}"]
        if not screenshot:
            return [], []

        artifact = ArtifactItem(
            type="screenshot",
            path=str(screenshot["path"]),
            metadata={
                "url": screenshot.get("url") or target_url,
                "description": screenshot.get("description"),
            },
        )
        observations = [screenshot["description"]] if screenshot.get("description") else []
        return [artifact], observations

    def _capture_with_adapter(self, screenshotter: Any, url: str, query: str) -> dict[str, Any] | None:
        if hasattr(screenshotter, "capture"):
            return screenshotter.capture(url, query=query)
        if hasattr(screenshotter, "invoke"):
            return screenshotter.invoke({"url": url, "query": query})
        if callable(screenshotter):
            return screenshotter(url)
        return None

    def _default_screenshotter(self, wants_screenshot: bool) -> Any | None:
        if not wants_screenshot:
            return None
        try:
            from app.agent.tools.adapters.playwright_screenshotter import PlaywrightScreenshotter
        except ImportError:
            return None
        return PlaywrightScreenshotter()

    def _first_url(self, search_results: list[dict[str, Any]]) -> str | None:
        fallback_url = None
        for result in search_results:
            url = result.get("url")
            if not url:
                continue
            fallback_url = fallback_url or url
            hostname = urlparse(url).hostname or ""
            if "bocha.cn" not in hostname:
                return url
        return fallback_url

    def _query_mentions_screenshot(self, query: str) -> bool:
        return any(keyword in query for keyword in ("截图", "截屏", "网页图", "页面图"))

    def _estimate_confidence(self, search_mode: str, evidence: list[EvidenceItem]) -> float:
        if search_mode == "offline_fallback":
            return 0.35
        if not evidence:
            return 0.4
        return round(sum(item.confidence or 0.7 for item in evidence) / len(evidence), 2)

    def _build_summary(
        self,
        query: str,
        search_results: list[dict[str, Any]],
        search_mode: str,
        screenshot_observations: list[str],
    ) -> str:
        if search_mode == "offline_fallback":
            return search_results[0]["content"] if search_results else f"无法检索“{query}”。"
        if not search_results:
            return f"围绕“{query}”完成网页检索，但没有返回可展示的网页结果。建议补充地点或时间，例如“成都今天暴雨预警”。"

        snippets = [
            f"{result['title']}：{result['content']}"
            for result in search_results[:3]
            if result.get("content")
        ]
        summary = f"围绕“{query}”完成网页检索。" + (" ".join(snippets) if snippets else "")
        if screenshot_observations:
            summary += f" 截图理解：{'；'.join(screenshot_observations)}"
        return summary
