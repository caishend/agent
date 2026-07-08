import unittest

from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.memory import MemoryTool


class MemoryToolTest(unittest.TestCase):
    def setUp(self):
        self.tool = MemoryTool()
        self.context = ToolContext(task_id=5, user_id=9, conversation_id=30)
        self.draft = {
            "status": "pending_user_confirmation",
            "title": "成都今天暴雨洪涝分析任务草稿",
            "disaster_type": "暴雨洪涝",
            "locations": ["成都"],
            "time_range": "今天",
            "known_info": [
                {"field": "灾害类型", "value": "暴雨洪涝"},
                {"field": "影响区域", "value": ["成都"]},
            ],
            "missing_info": ["受影响人口/设施"],
            "candidate_evidence": [
                {
                    "source": "browser",
                    "type": "web",
                    "content": "成都市气象台发布暴雨预警",
                    "confidence": 0.9,
                    "metadata": {"url": "https://example.com/warning"},
                }
            ],
            "source_message": "请分析成都今天暴雨洪涝灾害风险",
        }

    def test_rejects_unconfirmed_draft(self):
        result = self.tool.run(
            ToolInput(query="先别保存", params={"draft": self.draft}),
            self.context,
        )

        self.assertEqual(result.data["memory_status"], "waiting_user_confirmation")
        self.assertTrue(result.need_user_confirm)
        self.assertNotIn("formal_memory", self.context.metadata)

    def test_persists_confirmed_draft_into_context_memory(self):
        result = self.tool.run(
            ToolInput(
                query="确认保留这些信息",
                params={"draft": self.draft, "confirmed": True},
            ),
            self.context,
        )

        memory = result.data["formal_memory"]

        self.assertEqual(result.data["memory_status"], "persisted")
        self.assertFalse(result.need_user_confirm)
        self.assertEqual(memory["task_id"], 5)
        self.assertEqual(memory["title"], "成都今天暴雨洪涝分析任务草稿")
        self.assertEqual(memory["disaster_type"], "暴雨洪涝")
        self.assertEqual(memory["locations"], ["成都"])
        self.assertEqual(memory["status"], "confirmed")
        self.assertEqual(memory["version"], 1)
        self.assertEqual(self.context.metadata["formal_memory"], memory)
        self.assertTrue(self.context.metadata["confirmed_task"])

    def test_persists_selected_fields_only_when_provided(self):
        result = self.tool.run(
            ToolInput(
                query="只保留灾害类型和影响区域",
                params={
                    "draft": self.draft,
                    "confirmed": True,
                    "selected_fields": ["disaster_type", "locations"],
                },
            ),
            self.context,
        )

        memory = result.data["formal_memory"]

        self.assertEqual(memory["disaster_type"], "暴雨洪涝")
        self.assertEqual(memory["locations"], ["成都"])
        self.assertNotIn("time_range", memory)
        self.assertNotIn("candidate_evidence", memory)


if __name__ == "__main__":
    unittest.main()
