import unittest

from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.intent_router import IntentRouterTool


class IntentRouterToolTest(unittest.TestCase):
    def setUp(self):
        self.router = IntentRouterTool()
        self.context = ToolContext(task_id=1, user_id=7)

    def route(self, query, files=None, params=None):
        return self.router.run(
            ToolInput(query=query, files=files or [], params=params or {}),
            self.context,
        )

    def test_routes_general_knowledge_question_to_graphrag_only(self):
        result = self.route("为什么台风登陆后通常会减弱？")

        self.assertEqual(result.data["primary_intent"], "knowledge_or_general_qa")
        self.assertEqual(result.data["tools"], ["graphrag"])
        self.assertFalse(result.need_user_confirm)

    def test_routes_realtime_search_and_screenshot_to_browser(self):
        result = self.route("搜索今天的暴雨预警，并截图理解网页内容")

        self.assertIn("realtime_search", result.data["intents"])
        self.assertIn("browser_screenshot", result.data["intents"])
        self.assertEqual(result.data["tools"], ["browser"])
        self.assertFalse(result.need_user_confirm)

    def test_routes_remote_sensing_image_to_remote_sensing_tool(self):
        result = self.route(
            "识别这张遥感影像里的淹没区域",
            files=[{"name": "flood.tif", "type": "image/tiff"}],
        )

        self.assertEqual(result.data["primary_intent"], "remote_sensing_analysis")
        self.assertEqual(result.data["tools"], ["remote_sensing"])

    def test_disaster_analysis_creates_draft_before_risk_assessment(self):
        result = self.route("请分析成都暴雨洪涝灾害风险，并给出应急建议")

        self.assertEqual(result.data["primary_intent"], "disaster_analysis")
        self.assertIn("task_draft", result.data["tools"])
        self.assertIn("graphrag", result.data["tools"])
        self.assertNotIn("risk_assessment", result.data["tools"])
        self.assertTrue(result.need_user_confirm)
        self.assertEqual(result.data["next_step"], "confirm_task_draft")

    def test_confirmed_disaster_task_can_enter_risk_assessment(self):
        result = self.route(
            "这些信息已确认，开始风险评估",
            params={"confirmed_task": True},
        )

        self.assertEqual(result.data["primary_intent"], "risk_assessment")
        self.assertIn("risk_assessment", result.data["tools"])
        self.assertFalse(result.need_user_confirm)


if __name__ == "__main__":
    unittest.main()
