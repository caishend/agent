import unittest

from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.graphrag import GraphRAGTool


class FakeLangChainRetriever:
    def invoke(self, query):
        return [
            {
                "page_content": "暴雨会导致河流水位上涨，并增加城市低洼区内涝风险。",
                "metadata": {"source": "knowledge_base", "entity": "暴雨"},
            },
            {
                "page_content": "应急措施包括排查积水点、转移低洼区域人员、关注官方预警。",
                "metadata": {"source": "knowledge_base", "entity": "应急措施"},
            },
        ]


class FakeLegacyRetriever:
    def get_relevant_documents(self, query):
        return [
            {
                "page_content": "台风可能引发风暴潮、强降雨和城市内涝。",
                "metadata": {"source": "legacy_retriever"},
            }
        ]


class GraphRAGToolTest(unittest.TestCase):
    def setUp(self):
        self.tool = GraphRAGTool()
        self.context = ToolContext(task_id=11, user_id=2)

    def test_uses_langchain_retriever_when_provided(self):
        result = self.tool.run(
            ToolInput(
                query="为什么暴雨会引发洪涝，应该怎么办？",
                params={"retriever": FakeLangChainRetriever()},
            ),
            self.context,
        )

        self.assertEqual(result.data["retrieval_mode"], "langchain_retriever")
        self.assertIn("暴雨", result.summary)
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual(result.evidence[0].source, "knowledge_base")
        self.assertEqual(result.evidence[0].type, "retrieved_document")

    def test_supports_legacy_langchain_retriever_api(self):
        result = self.tool.run(
            ToolInput(
                query="台风会造成哪些风险？",
                params={"retriever": FakeLegacyRetriever()},
            ),
            self.context,
        )

        self.assertEqual(result.data["retrieval_mode"], "langchain_retriever")
        self.assertIn("风暴潮", result.summary)
        self.assertEqual(result.evidence[0].source, "legacy_retriever")

    def test_uses_graph_paths_as_reasoning_evidence(self):
        result = self.tool.run(
            ToolInput(
                query="解释暴雨洪涝形成机制",
                params={
                    "graph_paths": [
                        {
                            "nodes": ["持续强降雨", "河流水位上涨", "洪涝"],
                            "relation": "触发",
                            "confidence": 0.91,
                            "source": "neo4j",
                        }
                    ]
                },
            ),
            self.context,
        )

        self.assertEqual(result.data["retrieval_mode"], "graph_paths")
        self.assertIn("持续强降雨 → 河流水位上涨 → 洪涝", result.summary)
        self.assertEqual(result.evidence[0].type, "graph_path")
        self.assertEqual(result.evidence[0].confidence, 0.91)

    def test_falls_back_to_builtin_disaster_knowledge(self):
        result = self.tool.run(ToolInput(query="为什么暴雨会导致内涝？"), self.context)

        self.assertEqual(result.data["retrieval_mode"], "builtin_rules")
        self.assertGreater(len(result.evidence), 0)
        self.assertTrue(any("暴雨" in item.content for item in result.evidence))
        self.assertGreaterEqual(result.confidence, 0.6)


if __name__ == "__main__":
    unittest.main()
