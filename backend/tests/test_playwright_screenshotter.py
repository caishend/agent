import tempfile
import unittest
from pathlib import Path

from app.agent.tools.adapters.playwright_screenshotter import PlaywrightScreenshotter


class FakePage:
    def __init__(self):
        self.goto_args = None
        self.screenshot_args = None

    def goto(self, url, wait_until, timeout):
        self.goto_args = {"url": url, "wait_until": wait_until, "timeout": timeout}

    def title(self):
        return "暴雨预警页面"

    def screenshot(self, path, full_page):
        self.screenshot_args = {"path": path, "full_page": full_page}
        Path(path).write_bytes(b"fake screenshot")


class FakeBrowser:
    def __init__(self):
        self.page = FakePage()
        self.closed = False

    def new_page(self, viewport):
        self.viewport = viewport
        return self.page

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self):
        self.browser = FakeBrowser()
        self.launch_args = None

    def launch(self, headless):
        self.launch_args = {"headless": headless}
        return self.browser


class FakePlaywright:
    def __init__(self):
        self.chromium = FakeChromium()


class FakePlaywrightContext:
    def __init__(self):
        self.playwright = FakePlaywright()
        self.exited = False

    def __enter__(self):
        return self.playwright

    def __exit__(self, exc_type, exc, traceback):
        self.exited = True


class PlaywrightScreenshotterTest(unittest.TestCase):
    def test_captures_page_screenshot_to_output_dir(self):
        context = FakePlaywrightContext()
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshotter = PlaywrightScreenshotter(
                output_dir=temp_dir,
                playwright_factory=lambda: context,
            )

            result = screenshotter.capture("https://example.com/warning", query="暴雨预警")

            screenshot_path = Path(result["path"])
            self.assertTrue(screenshot_path.exists())
            self.assertEqual(result["url"], "https://example.com/warning")
            self.assertIn("暴雨预警页面", result["description"])
            self.assertEqual(context.playwright.chromium.launch_args["headless"], True)
            self.assertEqual(context.playwright.chromium.browser.page.goto_args["wait_until"], "networkidle")
            self.assertTrue(context.playwright.chromium.browser.closed)

    def test_rejects_non_http_url(self):
        screenshotter = PlaywrightScreenshotter(playwright_factory=lambda: FakePlaywrightContext())

        with self.assertRaises(ValueError):
            screenshotter.capture("file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
