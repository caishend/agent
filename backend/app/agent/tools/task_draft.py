"""临时任务文档工具。"""
from __future__ import annotations

from app.agent.tools.base_tool import BaseTool, ToolContext, ToolInput, ToolResult


class TaskDraftTool(BaseTool):
    name = "task_draft"
    description = "基于本轮对话整理临时任务文档，等待用户确认哪些信息需要保留。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        return ToolResult(
            summary=(
                "【临时任务文档（占位）】\n"
                "已根据当前对话整理灾害类型、区域、已知条件、缺失信息和候选证据。\n"
                "这些信息暂不写入正式任务记忆，需要用户确认后再沉淀。"
            ),
            need_user_confirm=True,
            data={
                "known_info": [],
                "missing_info": [],
                "candidate_evidence": [],
            },
        )
