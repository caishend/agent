"""Graph RAG 知识推理工具（占位实现）。"""
from app.agent.tools.base_tool import BaseTool


class GraphRAGTool(BaseTool):
    name = "graphrag"
    description = "基于灾害知识图谱进行因果推理，解释灾害原因与应对措施。"

    def run(self, query: str) -> str:
        # TODO: 接入 Microsoft GraphRAG + Neo4j
        # 示例：从 Neo4j 查询知识路径，调用 LLM 生成解释
        return (
            "【知识图谱推理结果（占位）】\n"
            "- 触发路径：持续强降雨 → 河流水位上涨 → 洪水\n"
            "- 历史记录：近10年该区域发生洪灾 5 次\n"
            "- 建议：启动二级应急响应，提前疏散低洼区域居民"
        )
