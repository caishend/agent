"""Playwright 网页截图适配器。"""
from __future__ import annotations

import hashlib
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


class PlaywrightScreenshotter:
    """使用 Playwright Chromium 打开网页并保存截图。"""

    def __init__(
        self,
        output_dir: str | Path = "data/screenshots",
        viewport: dict[str, int] | None = None,
        timeout_ms: int = 15_000,
        full_page: bool = True,
        headless: bool = True,
        playwright_factory: Callable[[], Any] | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.viewport = viewport or {"width": 1440, "height": 1200}
        self.timeout_ms = timeout_ms
        self.full_page = full_page
        self.headless = headless
        self.playwright_factory = playwright_factory

    def capture(self, url: str, query: str | None = None) -> dict[str, Any]:
        if sys.platform.startswith("win"):
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                pass
        self._validate_url(url)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = self.output_dir / self._filename_for(url)

        browser = None
        with self._sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            try:
                page = browser.new_page(viewport=self.viewport)
                response = page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
                title = page.title()
                try:
                    body_text = page.locator("body").inner_text(timeout=2_000)[:2000]
                except Exception:
                    body_text = ""
                page.screenshot(path=str(screenshot_path), full_page=self.full_page)
            finally:
                if browser:
                    browser.close()

        return {
            "path": str(screenshot_path),
            "url": url,
            "title": title,
            "status_code": response.status if response else None,
            "body_text": body_text,
            "description": self._build_description(title, url, query),
        }

    def _sync_playwright(self):
        if self.playwright_factory:
            return self.playwright_factory()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "Playwright 未安装。请先执行：pip install playwright，然后执行：playwright install chromium"
            ) from error
        return sync_playwright()

    def _validate_url(self, url: str) -> None:
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("PlaywrightScreenshotter 只允许截取 http/https 网页 URL")

    def _filename_for(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"screenshot_{timestamp}_{digest}.png"

    def _build_description(self, title: str, url: str, query: str | None) -> str:
        title_text = title or url
        if query:
            return f"已截取与“{query}”相关的网页截图：{title_text}"
        return f"已截取网页截图：{title_text}"
