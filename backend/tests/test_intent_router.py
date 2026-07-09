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

    def test_routes_disaster_knowledge_question_to_graphrag_only(self):
        result = self.route("为什么台风登陆后通常会减弱？")

        self.assertEqual(result.data["primary_intent"], "knowledge_or_general_qa")
        self.assertEqual(result.data["tools"], ["graphrag"])
        self.assertFalse(result.need_user_confirm)

    def test_routes_realtime_search_and_screenshot_to_browser(self):
        result = self.route("搜索今天的暴雨预警，并截图理解网页内容")

        self.assertIn("realtime_search", result.data["intents"])
        self.assertEqual(result.data["tools"], ["browser"])
        self.assertFalse(result.need_user_confirm)

    def test_routes_remote_sensing_image_to_remote_sensing_tool(self):
        result = self.route(
            "识别这张遥感影像里的淹没区域",
            files=[{"name": "flood.tif", "type": "image/tiff"}],
        )

        self.assertEqual(result.data["primary_intent"], "remote_sensing_analysis")
        self.assertEqual(result.data["tools"], ["remote_sensing"])

    def test_manual_disaster_analysis_runs_full_report_chain(self):
        result = self.route(
            "整合保存的对话记录和文档，联网搜索后生成灾害分析报告",
            params={"forced_tool": "disaster_analysis", "report_format": "docx"},
        )

        self.assertEqual(result.data["primary_intent"], "manual_disaster_analysis")
        self.assertEqual(
            result.data["tools"],
            ["browser", "graphrag", "task_draft", "memory", "risk_assessment", "graphrag_ingest", "report"],
        )
        self.assertFalse(result.need_user_confirm)
        self.assertEqual(result.data["next_step"], "generate_report")

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
