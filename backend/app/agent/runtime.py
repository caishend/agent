"""Agent 工具编排运行时。"""
from __future__ import annotations

from typing import Any

from app.agent.tools.base_tool import BaseTool, ToolContext, ToolInput, ToolResult
from app.agent.tools.browser import BrowserTool
from app.agent.tools.document import DocumentTool
from app.agent.tools.email import EmailTool
from app.agent.tools.graphrag import GraphRAGTool
from app.agent.tools.intent_router import IntentRouterTool
from app.agent.tools.memory import MemoryTool
from app.agent.tools.remote_sensing import RemoteSensingTool
from app.agent.tools.report import ReportTool
from app.agent.tools.risk_assessment import RiskAssessmentTool
from app.agent.tools.task_draft import TaskDraftTool


class AgentSessionStore:
    """MVP 内存会话存储；后续可替换为 task_document / tool_call 表。"""

    def __init__(self):
        self._metadata_by_task: dict[int, dict[str, Any]] = {}

    def metadata_for(self, task_id: int) -> dict[str, Any]:
        return self._metadata_by_task.setdefault(task_id, {})

    def clear(self, task_id: int) -> None:
        self._metadata_by_task.pop(task_id, None)


session_store = AgentSessionStore()


def tool_registry() -> dict[str, BaseTool]:
    return {
        "graphrag": GraphRAGTool(),
        "browser": BrowserTool(),
        "document": DocumentTool(),
        "remote_sensing": RemoteSensingTool(),
        "task_draft": TaskDraftTool(),
        "memory": MemoryTool(),
        "risk_assessment": RiskAssessmentTool(),
        "report": ReportTool(),
        "email": EmailTool(),
    }


def run_agent_once(
    task_id: int,
    user_id: int,
    message: str,
    files: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    metadata = session_store.metadata_for(task_id)
    context = ToolContext(task_id=task_id, user_id=user_id, metadata=metadata)
    tool_input = ToolInput(query=message, files=files or [], params=params or {})

    events: list[dict[str, Any]] = [{"type": "thinking", "content": "正在分析用户意图并规划工具调用..."}]
    router_result = IntentRouterTool().run(tool_input, context)
    tools_to_run = router_result.data.get("tools", ["graphrag"])
    events.append({"type": "intent", "content": router_result.to_text(), "data": router_result.data})

    results: dict[str, ToolResult] = {}
    for tool_name in tools_to_run:
        events.append({"type": "tool_call", "tool": tool_name, "content": f"调用工具：{tool_name}"})
        try:
            result = call_tool(tool_name, tool_input, context)
            results[tool_name] = result
            _update_session_from_result(tool_name, result, metadata)
            events.append(_tool_result_event(tool_name, result))
        except Exception as error:
            events.append(
                {
                    "type": "tool_result",
                    "tool": tool_name,
                    "content": f"工具调用失败：{error}",
                    "error": str(error),
                }
            )

    events.append({"type": "answer", "content": synthesize_answer(message, results)})
    return events


def confirm_task_draft(
    task_id: int,
    user_id: int,
    draft: dict[str, Any],
    selected_fields: list[str] | None = None,
) -> ToolResult:
    metadata = session_store.metadata_for(task_id)
    context = ToolContext(task_id=task_id, user_id=user_id, metadata=metadata)
    result = MemoryTool().run(
        ToolInput(
            query="确认保留这些任务信息",
            params={"draft": draft, "confirmed": True, "selected_fields": selected_fields},
        ),
        context,
    )
    _update_session_from_result("memory", result, metadata)
    return result


def call_tool(tool_name: str, tool_input: ToolInput, context: ToolContext) -> ToolResult:
    tools = tool_registry()
    tool = tools.get(tool_name)
    if not tool:
        raise ValueError(f"未知工具：{tool_name}")

    prepared_input = _prepare_tool_input(tool_name, tool_input, context.metadata)
    return tool.run(prepared_input, context)


def _prepare_tool_input(
    tool_name: str,
    tool_input: ToolInput,
    metadata: dict[str, Any],
) -> ToolInput:
    params = dict(tool_input.params or {})

    if tool_name == "memory" and "draft" not in params and metadata.get("last_draft"):
        params["draft"] = metadata["last_draft"]
    if tool_name == "graphrag" and "documents" not in params and metadata.get("documents"):
        params["documents"] = metadata["documents"]
    if tool_name == "risk_assessment" and "formal_memory" not in params and metadata.get("formal_memory"):
        params["formal_memory"] = metadata["formal_memory"]

    return ToolInput(query=tool_input.query, files=tool_input.files, params=params)


def _update_session_from_result(
    tool_name: str,
    result: ToolResult,
    metadata: dict[str, Any],
) -> None:
    if tool_name == "task_draft" and result.data.get("draft"):
        metadata["last_draft"] = result.data["draft"]
    if tool_name == "document" and result.data.get("documents"):
        metadata["documents"] = result.data["documents"]
    if tool_name == "memory" and result.data.get("formal_memory"):
        metadata["formal_memory"] = result.data["formal_memory"]
        metadata["confirmed_task"] = True
    if tool_name == "risk_assessment" and result.data.get("assessment"):
        metadata["risk_assessment"] = result.data["assessment"]


def _tool_result_event(tool_name: str, result: ToolResult) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool": tool_name,
        "content": result.to_text(),
        "data": result.data,
        "evidence": [item.__dict__ for item in result.evidence],
        "artifacts": [item.__dict__ for item in result.artifacts],
        "need_user_confirm": result.need_user_confirm,
    }


def synthesize_answer(message: str, results: dict[str, ToolResult]) -> str:
    if not results:
        return f"已收到问题：{message}。当前没有可用工具结果。"
    lines = [f"针对“{message}”，本轮工具分析结果如下："]
    for tool_name, result in results.items():
        lines.append(f"【{tool_name}】{result.summary}")
    return "\n".join(lines)
