import unittest

from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.intent_router import IntentRouterTool


class IntentRouterToolTest(unittest.TestCase):
    def setUp(self):
        self.router = IntentRouterTool(use_llm=False)
        self.context = ToolContext(task_id=1, user_id=7)

    def route(self, query, files=None, params=None):
        return self.router.run(
            ToolInput(query=query, files=files or [], params=params or {}),
            self.context,
        )

    def test_manual_research_routes_to_graphrag(self):
        result = self.route("为什么台风登陆后通常会减弱？", params={"forced_tool": "graphrag"})

        self.assertEqual(result.data["primary_intent"], "manual_graphrag")
        self.assertEqual(result.data["tools"], ["graphrag"])
        self.assertFalse(result.need_user_confirm)

    def test_routes_realtime_search_and_screenshot_to_browser(self):
        result = self.route("搜索今天的暴雨预警，并截图理解网页内容")

        self.assertTrue({"realtime_search", "browser_search"} & set(result.data["intents"]))
        self.assertEqual(result.data["tools"], ["browser"])
        self.assertFalse(result.need_user_confirm)

    def test_routes_remote_sensing_image_to_remote_sensing_tool(self):
        result = self.route(
            "识别这张遥感影像里的淹没区域",
            files=[{"name": "flood.tif", "type": "image/tiff"}],
        )

        self.assertEqual(result.data["primary_intent"], "remote_sensing_analysis")
        self.assertEqual(result.data["tools"], ["remote_sensing"])

    def test_manual_disaster_analysis_never_generates_report(self):
        result = self.route(
            "成都暴雨灾害评估",
            params={"forced_tool": "disaster_analysis"},
        )

        self.assertEqual(result.data["primary_intent"], "manual_disaster_analysis")
        self.assertEqual(result.data["tools"], ["browser", "graphrag", "risk_assessment"])
        self.assertEqual(result.data["next_step"], "run_risk_assessment")
        self.assertNotIn("report", result.data["tools"])

    def test_manual_report_only_generates_report(self):
        result = self.route(
            "生成成都暴雨灾害评估报告",
            params={"forced_tool": "report"},
        )

        self.assertEqual(result.data["primary_intent"], "manual_report")
        self.assertEqual(result.data["tools"], ["report"])
        self.assertEqual(result.data["next_step"], "generate_report")


if __name__ == "__main__":
    unittest.main()
