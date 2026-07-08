"""多源灾害风险评估工具。"""
from app.agent.tools.base_tool import BaseTool, ToolContext, ToolResult


class RiskAssessmentTool(BaseTool):
    name = "risk_assessment"
    description = "融合图谱、浏览器、文档、遥感等证据，生成风险评分、等级、原因和建议。"

    def run(self, query: str, context: ToolContext | None = None) -> ToolResult:
        # TODO: 基于 ToolResult evidence 做加权融合
        return ToolResult(
            summary=(
                "【风险评估结果（占位）】\n"
                "风险等级：高风险\n"
                "风险评分：0.87\n"
                "主要原因：持续强降雨、历史灾害频发、疑似受灾区域扩大\n"
                "建议：启动应急响应，优先核验低洼区域人员与道路通行情况。"
            ),
            evidence=[
                {
                    "source": "risk_assessment",
                    "type": "fusion",
                    "content": "融合多源证据后得到高风险结论",
                    "confidence": 0.87,
                }
            ],
            confidence=0.87,
            data={"risk_score": 0.87, "risk_level": "高风险"},
        )
