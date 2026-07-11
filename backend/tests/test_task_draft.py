import unittest

from app.agent.tools.base_tool import EvidenceItem, ToolContext, ToolInput
from app.agent.tools.task_draft import TaskDraftTool


class TaskDraftToolTest(unittest.TestCase):
    def setUp(self):
        self.tool = TaskDraftTool()
        self.context = ToolContext(task_id=3, user_id=8, conversation_id=21)

    def test_builds_registerable_task_info_from_disaster_query(self):
        result = self.tool.run(
            ToolInput(query="请分析成都今天暴雨洪涝灾害风险，并给出应急建议"),
            self.context,
        )

        draft = result.data["draft"]

        self.assertFalse(result.need_user_confirm)
        self.assertEqual(draft["status"], "ready_to_register")
        self.assertEqual(draft["disaster_type"], "暴雨洪涝")
        self.assertEqual(draft["locations"], ["成都"])
        self.assertEqual(draft["time_range"], "今天")
        self.assertIn("成都", draft["title"])
        self.assertIn("暴雨洪涝", draft["title"])
        self.assertIn("请分析成都今天暴雨洪涝灾害风险，并给出应急建议", draft["source_message"])

    def test_lists_missing_fields_when_query_is_incomplete(self):
        result = self.tool.run(ToolInput(query="帮我分析一下灾害风险"), self.context)

        draft = result.data["draft"]

        self.assertEqual(draft["disaster_type"], "未知")
        self.assertEqual(draft["locations"], [])
        self.assertIn("灾害类型", draft["missing_info"])
        self.assertIn("影响区域", draft["missing_info"])
        self.assertIn("时间范围", draft["missing_info"])

    def test_preserves_candidate_evidence_from_params(self):
        evidence = EvidenceItem(
            source="browser",
            type="web",
            content="成都市气象台发布暴雨预警",
            confidence=0.9,
            metadata={"url": "https://example.com/warning"},
        )

        result = self.tool.run(
            ToolInput(
                query="分析成都暴雨风险",
                params={"candidate_evidence": [evidence]},
            ),
            self.context,
        )

        candidate_evidence = result.data["draft"]["candidate_evidence"]

        self.assertEqual(candidate_evidence[0]["source"], "browser")
        self.assertEqual(candidate_evidence[0]["content"], "成都市气象台发布暴雨预警")


if __name__ == "__main__":
    unittest.main()
