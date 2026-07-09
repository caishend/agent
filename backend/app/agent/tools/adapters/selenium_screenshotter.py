"""Optional Selenium screenshot fallback."""
from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class SeleniumScreenshotter:
    """Capture a full-page screenshot with Selenium Chrome CDP."""

    def __init__(
        self,
        output_dir: str | Path = "data/screenshots",
        chrome_binary_path: str | None = None,
        chrome_driver_path: str | None = None,
        timeout_seconds: int = 20,
        headless: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.chrome_binary_path = chrome_binary_path or os.getenv("CHROME_BINARY_PATH")
        self.chrome_driver_path = chrome_driver_path or os.getenv("CHROME_DRIVER_PATH")
        self.timeout_seconds = timeout_seconds
        self.headless = headless

    def capture(self, url: str, query: str | None = None) -> dict[str, Any]:
        self._validate_url(url)
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
        except ImportError as error:
            raise RuntimeError("Selenium 未安装：请安装 selenium，或继续使用 Playwright 截图。") from error

        self.output_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = self.output_dir / self._filename_for(url)

        options = Options()
        if self.chrome_binary_path:
            options.binary_location = self.chrome_binary_path
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-notifications")
        options.add_argument("--window-size=1440,1200")

        service = Service(executable_path=self.chrome_driver_path) if self.chrome_driver_path else None
        driver = webdriver.Chrome(service=service, options=options) if service else webdriver.Chrome(options=options)
        try:
            driver.set_page_load_timeout(self.timeout_seconds)
            driver.get(url)
            title = driver.title
            try:
                body_text = driver.find_element("tag name", "body").text[:2000]
            except Exception:
                body_text = ""
            result = driver.execute_cdp_cmd(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
            )
            screenshot_path.write_bytes(base64.b64decode(result["data"]))
        finally:
            driver.quit()

        return {
            "path": str(screenshot_path),
            "url": url,
            "title": title,
            "body_text": body_text,
            "description": self._build_description(title, url, query),
        }

    def _validate_url(self, url: str) -> None:
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("SeleniumScreenshotter 只允许截图 http/https 网页 URL")

    def _filename_for(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"selenium_{timestamp}_{digest}.png"

    def _build_description(self, title: str, url: str, query: str | None) -> str:
        title_text = title or url
        if query:
            return f"已用 Selenium 截取与“{query}”相关的网页截图：{title_text}"
        return f"已用 Selenium 截取网页截图：{title_text}"
