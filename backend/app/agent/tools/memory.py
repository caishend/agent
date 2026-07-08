"""正式任务记忆写入工具。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agent.tools.base_tool import BaseTool, ToolContext, ToolInput, ToolResult


class MemoryTool(BaseTool):
    name = "memory"
    description = "在用户确认后，将临时任务草稿中的必要信息写入正式任务记忆。"

    default_persisted_fields = (
        "title",
        "disaster_type",
        "locations",
        "time_range",
        "known_info",
        "missing_info",
        "candidate_evidence",
        "source_message",
    )

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        params = tool_input.params or {}
        draft = params.get("draft") or {}
        confirmed = self._is_confirmed(tool_input.query, params)

        if not draft:
            return ToolResult(
                summary="未收到可写入的临时任务草稿，请先生成并确认草稿。",
                need_user_confirm=True,
                confidence=0.3,
                data={"memory_status": "missing_draft"},
            )

        if not confirmed:
            return ToolResult(
                summary="临时任务草稿尚未确认，暂不写入正式任务记忆。",
                need_user_confirm=True,
                confidence=0.75,
                data={"memory_status": "waiting_user_confirmation", "draft": draft},
            )

        formal_memory = self._build_formal_memory(
            draft=draft,
            context=context,
            selected_fields=params.get("selected_fields"),
        )
        if context:
            context.metadata["formal_memory"] = formal_memory
            context.metadata["confirmed_task"] = True

        return ToolResult(
            summary=f"已写入正式任务记忆：{formal_memory.get('title', '未命名任务')}。",
            need_user_confirm=False,
            confidence=0.88,
            data={"memory_status": "persisted", "formal_memory": formal_memory},
        )

    def _is_confirmed(self, query: str, params: dict[str, Any]) -> bool:
        if params.get("confirmed") or params.get("confirmed_task") or params.get("task_confirmed"):
            return True
        rejection_words = ("先别", "不要", "暂不", "别保存", "不保存", "别写入")
        if any(word in query for word in rejection_words):
            return False
        confirmation_words = ("确认", "已确认", "保留", "保存", "可以开始", "写入")
        return any(word in query for word in confirmation_words)

    def _build_formal_memory(
        self,
        draft: dict[str, Any],
        context: ToolContext | None,
        selected_fields: list[str] | None,
    ) -> dict[str, Any]:
        fields = selected_fields or list(self.default_persisted_fields)
        formal_memory = {
            "task_id": context.task_id if context else None,
            "user_id": context.user_id if context else None,
            "conversation_id": context.conversation_id if context else None,
            "status": "confirmed",
            "version": self._next_version(context),
        }

        for field in fields:
            if field in draft:
                formal_memory[field] = deepcopy(draft[field])

        return formal_memory

    def _next_version(self, context: ToolContext | None) -> int:
        if not context:
            return 1
        previous_memory = context.metadata.get("formal_memory")
        if not previous_memory:
            return 1
        return int(previous_memory.get("version", 0)) + 1
