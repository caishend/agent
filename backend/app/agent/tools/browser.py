"""Browser search, page screenshot, and screenshot observation tool."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.agent.tools.base_tool import ArtifactItem, BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult


class BrowserTool(BaseTool):
    name = "browser"
    description = "实时搜索互联网信息，打开网页并截取真实网页截图。"
    blocked_domains = (
        "mala.cn",
        "discuz",
        "archive",
        "bbs.",
        "forum.",
    )
    blocked_url_markers = (
        "/archive/",
        "tid=",
        "forum.php",
        "thread-",
        "mod=viewthread",
        "404",
    )
    preferred_domains = (
        "gov.cn",
        "cma.cn",
        "weather.com.cn",
        "mem.gov.cn",
        "sc.gov.cn",
        "chengdu.gov.cn",
        "news.cn",
        "xinhuanet.com",
        "people.com.cn",
        "cctv.com",
        "thepaper.cn",
        "chinanews.com.cn",
    )

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        query = tool_input.query.strip()
        search_query = self._prepare_search_query(query)
        params = tool_input.params or {}
        provided_search_tool = params.get("search_tool")
        search_tool = provided_search_tool or self._default_search_tool()

        if search_tool:
            try:
                raw_results = self._search_with_tool(search_tool, search_query)
                search_mode = "langchain_search_tool" if provided_search_tool else type(search_tool).__name__
            except Exception as error:
                raw_results = self._offline_fallback_results(search_query, error=str(error))
                search_mode = "offline_fallback"
        else:
            raw_results = self._offline_fallback_results(search_query)
            search_mode = "offline_fallback"

        search_results = self._normalize_search_results(raw_results)
        evidence = self._build_evidence(search_results)
        artifacts, screenshot_observations = self._capture_screenshots_if_needed(query, search_results, params)
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
        for phrase in ("给我一张", "发给我", "给我", "一张", "截图", "截屏", "网页截图", "的图片", "图片"):
            cleaned = cleaned.replace(phrase, " ")
        cleaned = " ".join(cleaned.split())
        cleaned = cleaned.strip(" 的，。,. ")
        if cleaned in {"天气", "天气预报"}:
            cleaned = "当地天气预报"
        if "暴雨" in cleaned and not any(word in cleaned for word in ("预警", "最新", "新闻", "通报")):
            cleaned = f"{cleaned} 最新预警 新闻"
        return cleaned or query

    def _search_with_tool(self, search_tool: Any, query: str) -> Any:
        if hasattr(search_tool, "invoke"):
            try:
                return search_tool.invoke(query, exclude="mala.cn|discuz.net|xichang.mala.cn")
            except TypeError:
                return search_tool.invoke(query)
        if hasattr(search_tool, "run"):
            return search_tool.run(query)
        if callable(search_tool):
            return search_tool(query)
        return []

    def _offline_fallback_results(self, query: str, error: str | None = None) -> list[dict[str, Any]]:
        content = f"未配置实时搜索工具，暂时无法联网检索“{query}”。请配置 Bocha/Tavily/SerpAPI 后重试。"
        if error:
            content = f"实时搜索调用失败：{error}。已切换为离线提示，无法联网检索“{query}”。"
        return [{"title": "离线搜索提示", "url": None, "content": content}]

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
        return [
            EvidenceItem(
                source=result["title"],
                type="web",
                content=result["content"],
                confidence=0.82 if result.get("url") else 0.55,
                metadata={"url": result.get("url"), **result.get("metadata", {})},
            )
            for result in search_results
        ]

    def _capture_screenshots_if_needed(
        self,
        query: str,
        search_results: list[dict[str, Any]],
        params: dict[str, Any],
    ) -> tuple[list[ArtifactItem], list[str]]:
        wants_screenshot = bool(params.get("capture_screenshot")) or self._query_mentions_screenshot(query)
        screenshotter = params.get("screenshotter") or self._default_screenshotter(wants_screenshot)
        if not wants_screenshot:
            return [], []

        candidate_urls = self._candidate_urls(search_results, query)
        if not candidate_urls:
            return [], ["没有可截图的搜索结果 URL。"]

        observations: list[str] = []
        screenshot = None
        target_url = candidate_urls[0]
        for index, url in enumerate(candidate_urls[:5], start=1):
            target_url = url
            if screenshotter:
                try:
                    screenshot = self._capture_with_adapter(screenshotter, url, query)
                    if self._is_valid_screenshot(screenshot):
                        break
                    observations.append(f"第 {index} 个网页截图无效或被拦截，已尝试下一个来源：{url}")
                    screenshot = None
                except Exception as error:
                    observations.append(f"第 {index} 个网页 Playwright 截图失败：{type(error).__name__}: {error}")

            try:
                screenshot = self._capture_with_adapter(self._selenium_screenshotter(), url, query)
                if self._is_valid_screenshot(screenshot):
                    observations.append("已切换 Selenium 兜底截图。")
                    break
                observations.append(f"第 {index} 个网页 Selenium 截图无效或被拦截，已尝试下一个来源：{url}")
                screenshot = None
            except Exception as error:
                observations.append(f"第 {index} 个网页截图失败：{type(error).__name__}: {error}")

        if not screenshot:
            return [], observations or ["没有获得有效网页截图。"]

        artifact = ArtifactItem(
            type="screenshot",
            path=str(screenshot["path"]),
            metadata={
                "url": screenshot.get("url") or target_url,
                "description": screenshot.get("description"),
            },
        )
        if screenshot.get("description"):
            observations.append(screenshot["description"])
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

    def _selenium_screenshotter(self) -> Any:
        from app.agent.tools.adapters.selenium_screenshotter import SeleniumScreenshotter

        return SeleniumScreenshotter()

    def _candidate_urls(self, search_results: list[dict[str, Any]], query: str = "") -> list[str]:
        candidates: list[tuple[int, str]] = []
        seen = set()
        for result in search_results:
            url = result.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            hostname = (urlparse(url).hostname or "").lower()
            title = str(result.get("title") or "").lower()
            content = str(result.get("content") or "").lower()
            if "bocha.cn" in hostname:
                continue
            if self._is_blocked_url(url):
                continue
            score = 0
            if any(domain in hostname for domain in self.preferred_domains):
                score += 20
            if any(keyword in title + content for keyword in ("暴雨", "预警", "气象", "应急", "成都")):
                score += 5
            candidates.append((score, url))
        candidates.sort(key=lambda item: item[0], reverse=True)
        urls = [url for _, url in candidates]
        for fallback_url in self._authoritative_fallback_urls(query):
            if fallback_url not in urls:
                urls.append(fallback_url)
        return urls

    def _is_blocked_url(self, url: str) -> bool:
        lowered_url = url.lower()
        hostname = (urlparse(url).hostname or "").lower()
        return any(marker in hostname or marker in lowered_url for marker in (*self.blocked_domains, *self.blocked_url_markers))

    def _authoritative_fallback_urls(self, query: str) -> list[str]:
        urls = []
        if "成都" in query:
            urls.append("https://www.weather.com.cn/weather1d/101270101.shtml")
            urls.append("https://www.cma.gov.cn/")
            urls.append("https://www.chengdu.gov.cn/")
        if any(keyword in query for keyword in ("暴雨", "预警", "天气", "气象")):
            urls.append("https://www.weather.com.cn/alarm/")
            urls.append("https://www.cma.gov.cn/")
        return urls

    def _is_valid_screenshot(self, screenshot: dict[str, Any] | None) -> bool:
        if not screenshot or not screenshot.get("path"):
            return False
        text = f"{screenshot.get('title') or ''}\n{screenshot.get('body_text') or ''}".lower()
        status_code = screenshot.get("status_code")
        if isinstance(status_code, int) and status_code >= 400:
            return False
        blocked_markers = (
            "网页不见鸟",
            "请求不合法",
            "已被网站管理员设置拦截",
            "访问频率过高",
            "404",
            "not found",
            "页面不存在",
            "网页不存在",
            "captcha",
            "安全验证",
            "403 forbidden",
            "access denied",
        )
        return not any(marker in text for marker in blocked_markers)

    def _query_mentions_screenshot(self, query: str) -> bool:
        normalized_query = query.lower()
        return any(
            keyword in normalized_query
            for keyword in ("截图", "截屏", "网页图", "页面图", "screenshot", "capture", "鎴浘")
        )

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
            return f"围绕“{query}”完成网页检索，但没有返回可展示的网页结果。"

        snippets = [
            f"{result['title']}：{result['content']}"
            for result in search_results[:3]
            if result.get("content")
        ]
        summary = f"围绕“{query}”完成网页检索。" + (" ".join(snippets) if snippets else "")
        if screenshot_observations:
            summary += f" 截图状态：{'；'.join(screenshot_observations)}"
        return summary
