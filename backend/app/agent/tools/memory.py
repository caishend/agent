"""正式任务记忆写入工具。"""
from __future__ import annotations

from app.agent.tools.base_tool import BaseTool, ToolContext, ToolInput, ToolResult


class MemoryTool(BaseTool):
    name = "memory"
    description = "在用户确认后，将临时任务文档中的必要信息写入正式任务记忆。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        # TODO: 写入 task_document 表并记录版本
        return ToolResult(
            summary="【任务记忆（占位）】已接收用户确认，候选信息将写入正式任务记忆。",
            data={"memory_status": "pending_persistence"},
        )
