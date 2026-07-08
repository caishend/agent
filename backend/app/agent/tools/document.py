"""文档解析工具（占位实现）。"""
from __future__ import annotations

from app.agent.tools.base_tool import BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult


class DocumentTool(BaseTool):
    name = "document"
    description = "解析用户上传的 PDF/Word/TXT 文档，提取关键信息写入任务记忆。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        # TODO: 接入 PyMuPDF + LangChain TextSplitter + Embedding
        return ToolResult(
            summary="【文档解析结果（占位）】已提取关键信息，先进入临时任务文档，等待用户确认是否保留。",
            evidence=[
                EvidenceItem(
                    source="uploaded_document",
                    type="document",
                    content="已识别灾害类型、地点、已知条件和缺失信息。",
                    confidence=0.80,
                )
            ],
            confidence=0.80,
            need_user_confirm=True,
        )
