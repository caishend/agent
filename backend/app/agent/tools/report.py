"""报告生成工具（占位实现）。"""
from app.agent.tools.base_tool import ArtifactItem, BaseTool, ToolContext, ToolInput, ToolResult


class ReportTool(BaseTool):
    name = "report"
    description = "将分析结论整合为结构化 PDF 灾害评估报告。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        # TODO: 接入 ReportLab + Jinja2 模板生成 PDF
        return ToolResult(
            summary="【报告生成（占位）】报告已生成，路径：data/reports/task_xxx.pdf",
            artifacts=[
                ArtifactItem(
                    type="report",
                    path="data/reports/task_xxx.pdf",
                    metadata={"format": "pdf"},
                )
            ],
        )
