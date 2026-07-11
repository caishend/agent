"""正式任务记忆写入工具。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agent.tools.base_tool import BaseTool, ToolContext, ToolInput, ToolResult


class MemoryTool(BaseTool):
    name = "memory"
    description = "将整理出的任务信息直接写入正式任务记忆。"

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
                summary="未收到可写入的任务信息。",
                need_user_confirm=False,
                confidence=0.3,
                data={"memory_status": "missing_draft"},
            )

        if not confirmed:
            return ToolResult(
                summary="用户明确要求不保存，本轮任务信息未写入记忆。",
                need_user_confirm=False,
                confidence=0.75,
                data={"memory_status": "skipped_by_user", "draft": draft},
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
            summary=f"已登记任务信息：{formal_memory.get('title', '未命名任务')}。",
            need_user_confirm=False,
            confidence=0.88,
            data={"memory_status": "persisted", "formal_memory": formal_memory},
        )

    def _is_confirmed(self, query: str, params: dict[str, Any]) -> bool:
        rejection_words = ("先别", "不要", "暂不", "别保存", "不保存", "别写入")
        if any(word in query for word in rejection_words):
            return False
        return True

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
