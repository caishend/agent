"""Graph RAG 知识推理工具（占位实现）。"""
from __future__ import annotations

from app.agent.tools.base_tool import BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult


class GraphRAGTool(BaseTool):
    name = "graphrag"
    description = "基于灾害知识图谱进行因果推理，解释灾害原因与应对措施。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        # TODO: 接入 Microsoft GraphRAG + Neo4j
        # 示例：从 Neo4j 查询知识路径，调用 LLM 生成解释
        return ToolResult(
            summary=(
                "【知识图谱推理结果（占位）】\n"
                "- 触发路径：持续强降雨 → 河流水位上涨 → 洪水\n"
                "- 历史记录：近10年该区域发生洪灾 5 次\n"
                "- 建议：启动二级应急响应，提前疏散低洼区域居民"
            ),
            evidence=[
                EvidenceItem(
                    source="disaster_knowledge_graph",
                    type="graph_path",
                    content="持续强降雨 → 河流水位上涨 → 洪水 → 人员转移",
                    confidence=0.86,
                )
            ],
            confidence=0.86,
        )
