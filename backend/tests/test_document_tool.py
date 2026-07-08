import tempfile
import unittest
from pathlib import Path

from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.document import DocumentTool


class FakeLangChainDocument:
    def __init__(self, page_content, metadata=None):
        self.page_content = page_content
        self.metadata = metadata or {}


class FakeLangChainLoader:
    def load(self):
        return [
            FakeLangChainDocument(
                "成都市暴雨洪涝应急预案要求关注低洼区域、学校和医院。",
                {"source": "plan.pdf", "page": 1},
            ),
            FakeLangChainDocument(
                "当气象台发布暴雨红色预警时，应组织人员转移并加强交通管制。",
                {"source": "plan.pdf", "page": 2},
            ),
        ]


class DocumentToolTest(unittest.TestCase):
    def setUp(self):
        self.tool = DocumentTool()
        self.context = ToolContext(task_id=15, user_id=6)

    def test_uses_langchain_loader_when_provided(self):
        result = self.tool.run(
            ToolInput(
                query="总结文档里的暴雨应急要点",
                params={"loader": FakeLangChainLoader()},
            ),
            self.context,
        )

        self.assertEqual(result.data["document_mode"], "langchain_loader")
        self.assertEqual(len(result.data["documents"]), 2)
        self.assertEqual(result.evidence[0].source, "plan.pdf")
        self.assertIn("暴雨洪涝", result.summary)
        self.assertTrue(result.need_user_confirm)

    def test_accepts_inline_text_documents(self):
        result = self.tool.run(
            ToolInput(
                query="提取关键信息",
                params={
                    "documents": [
                        {
                            "content": "成都今天暴雨红色预警，低洼区域存在内涝风险。",
                            "metadata": {"source": "manual_input"},
                        }
                    ]
                },
            ),
            self.context,
        )

        self.assertEqual(result.data["document_mode"], "provided_documents")
        self.assertEqual(result.data["documents"][0]["source"], "manual_input")
        self.assertIn("暴雨红色预警", result.data["key_points"][0])

    def test_loads_txt_file_from_tool_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "warning.txt"
            file_path.write_text("北京暴雨预警，山区存在滑坡风险。", encoding="utf-8")

            result = self.tool.run(
                ToolInput(
                    query="解析上传文档",
                    files=[{"path": str(file_path), "name": "warning.txt"}],
                ),
                self.context,
            )

        self.assertEqual(result.data["document_mode"], "file_loader")
        self.assertEqual(result.data["documents"][0]["source"], "warning.txt")
        self.assertIn("滑坡风险", result.summary)

    def test_returns_missing_document_when_no_input(self):
        result = self.tool.run(ToolInput(query="解析文档"), self.context)

        self.assertTrue(result.need_user_confirm)
        self.assertEqual(result.data["document_mode"], "missing_document")


if __name__ == "__main__":
    unittest.main()
