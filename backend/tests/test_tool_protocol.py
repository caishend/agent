import unittest

from app.agent.tools.base_tool import (
    ArtifactItem,
    EvidenceItem,
    ToolContext,
    ToolInput,
    ToolResult,
)


class ToolProtocolTest(unittest.TestCase):
    def test_tool_input_keeps_query_and_payload_defaults(self):
        tool_input = ToolInput(query="分析洪水风险")

        self.assertEqual(tool_input.query, "分析洪水风险")
        self.assertEqual(tool_input.files, [])
        self.assertEqual(tool_input.params, {})

    def test_tool_result_serializes_structured_evidence_and_artifacts(self):
        result = ToolResult(
            summary="识别到暴雨预警",
            evidence=[
                EvidenceItem(
                    source="browser",
                    type="web",
                    content="气象局发布暴雨红色预警",
                    confidence=0.95,
                    metadata={"url": "https://example.com/warning"},
                )
            ],
            artifacts=[
                ArtifactItem(
                    type="screenshot",
                    path="data/screenshots/warning.png",
                    metadata={"origin": "browser"},
                )
            ],
            confidence=0.9,
            need_user_confirm=True,
            data={"intent": "realtime_search"},
        )

        payload = result.to_dict()

        self.assertEqual(payload["summary"], "识别到暴雨预警")
        self.assertEqual(payload["evidence"][0]["source"], "browser")
        self.assertEqual(payload["artifacts"][0]["path"], "data/screenshots/warning.png")
        self.assertTrue(payload["need_user_confirm"])
        self.assertEqual(payload["data"]["intent"], "realtime_search")

    def test_tool_result_text_mentions_confidence_and_confirmation(self):
        result = ToolResult(
            summary="生成临时任务文档",
            confidence=0.8,
            need_user_confirm=True,
        )

        text = result.to_text()

        self.assertIn("生成临时任务文档", text)
        self.assertIn("可信度：0.80", text)
        self.assertIn("需要用户确认", text)

    def test_context_metadata_defaults_are_isolated(self):
        first = ToolContext()
        second = ToolContext()

        first.metadata["key"] = "value"

        self.assertEqual(second.metadata, {})


if __name__ == "__main__":
    unittest.main()
