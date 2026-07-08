import unittest

from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.browser import BrowserTool


class FakeLangChainSearchTool:
    def invoke(self, query):
        return [
            {
                "title": "成都市暴雨红色预警",
                "url": "https://example.com/warning",
                "content": "成都市气象台发布暴雨红色预警，局地降雨量可能超过150毫米。",
            },
            {
                "title": "城市内涝风险提示",
                "url": "https://example.com/flood",
                "snippet": "低洼路段存在积水和交通中断风险。",
            },
        ]


class FakeRunSearchTool:
    def run(self, query):
        return "中国气象局：目标区域未来24小时存在暴雨预警。"


class FakeScreenshotter:
    def capture(self, url, query=None):
        return {
            "path": "data/screenshots/warning.png",
            "url": url,
            "description": "截图中包含暴雨红色预警地图",
        }


class BrowserToolTest(unittest.TestCase):
    def setUp(self):
        self.tool = BrowserTool()
        self.context = ToolContext(task_id=12, user_id=4)

    def test_uses_langchain_search_tool_when_provided(self):
        result = self.tool.run(
            ToolInput(
                query="搜索成都今天暴雨预警",
                params={"search_tool": FakeLangChainSearchTool()},
            ),
            self.context,
        )

        self.assertEqual(result.data["search_mode"], "langchain_search_tool")
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual(result.evidence[0].source, "成都市暴雨红色预警")
        self.assertEqual(result.evidence[0].metadata["url"], "https://example.com/warning")
        self.assertIn("暴雨红色预警", result.summary)

    def test_supports_legacy_run_search_tool_api(self):
        result = self.tool.run(
            ToolInput(
                query="搜索未来24小时暴雨预警",
                params={"search_tool": FakeRunSearchTool()},
            ),
            self.context,
        )

        self.assertEqual(result.data["search_mode"], "langchain_search_tool")
        self.assertEqual(result.evidence[0].source, "web_search")
        self.assertIn("未来24小时", result.evidence[0].content)

    def test_captures_screenshot_when_requested(self):
        result = self.tool.run(
            ToolInput(
                query="搜索成都暴雨预警并截图理解网页",
                params={
                    "search_tool": FakeLangChainSearchTool(),
                    "screenshotter": FakeScreenshotter(),
                    "capture_screenshot": True,
                },
            ),
            self.context,
        )

        self.assertEqual(result.artifacts[0].type, "screenshot")
        self.assertEqual(result.artifacts[0].path, "data/screenshots/warning.png")
        self.assertEqual(result.artifacts[0].metadata["url"], "https://example.com/warning")
        self.assertIn("截图中包含暴雨红色预警地图", result.data["screenshot_observations"][0])

    def test_uses_default_screenshotter_when_not_provided(self):
        class BrowserToolWithDefaultScreenshotter(BrowserTool):
            def _default_screenshotter(self, wants_screenshot):
                return FakeScreenshotter() if wants_screenshot else None

        result = BrowserToolWithDefaultScreenshotter().run(
            ToolInput(
                query="搜索成都暴雨预警并截图",
                params={"search_tool": FakeLangChainSearchTool()},
            ),
            self.context,
        )

        self.assertEqual(result.artifacts[0].type, "screenshot")
        self.assertEqual(result.artifacts[0].path, "data/screenshots/warning.png")

    def test_falls_back_to_offline_search_hint(self):
        result = self.tool.run(ToolInput(query="搜索北京暴雨预警"), self.context)

        self.assertEqual(result.data["search_mode"], "offline_fallback")
        self.assertGreater(len(result.evidence), 0)
        self.assertIn("未配置实时搜索工具", result.summary)


if __name__ == "__main__":
    unittest.main()
