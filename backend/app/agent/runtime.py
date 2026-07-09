"""Agent tool orchestration runtime."""
from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from app.agent.llm import stream_llm_answer
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


def _chunk_text(text: str, size: int = 8) -> Iterator[str]:
    for index in range(0, len(text), size):
        yield text[index : index + size]


def _artifact_public_url(artifact_path: str, artifact_type: str) -> str:
    normalized = str(artifact_path or "").replace("\\", "/")
    filename = normalized.rsplit("/", 1)[-1]
    if artifact_type == "screenshot" and filename:
        return f"/artifacts/screenshots/{filename}"
    if artifact_type == "report" and filename:
        return f"/artifacts/reports/{filename}"
    marker = "data/remote_sensing/"
    if artifact_type in {"remote_sensing_overlay", "object_detection"} and marker in normalized:
        return "/artifacts/remote-sensing/" + normalized.split(marker, 1)[1]
    return normalized


def _image_result_appendix(results: dict[str, ToolResult]) -> str:
    result = results.get("remote_sensing")
    if not result or result.data.get("remote_sensing_status") != "analyzed":
        return ""

    aggregate = result.data.get("aggregate") or {}
    images = result.data.get("images") or []
    artifacts = [item.__dict__ for item in result.artifacts]
    overlay_urls = [
        _artifact_public_url(item.get("path", ""), item.get("type", ""))
        for item in artifacts
        if item.get("type") == "remote_sensing_overlay"
    ]
    detection_urls = [
        _artifact_public_url(item.get("path", ""), item.get("type", ""))
        for item in artifacts
        if item.get("type") == "object_detection"
    ]

    lines = ["", "### 图像处理结果"]
    lines.append(f"- 模型状态：{images[0].get('model_status', 'unknown') if images else 'unknown'}")
    if images and images[0].get("gate"):
        lines.append(f"- 门控结果：{images[0]['gate']}")
    lines.append(f"- 疑似灾害类型：{aggregate.get('affected_class_name', 'unknown')}")
    lines.append(f"- 影响区域占比：{float(aggregate.get('affected_ratio') or 0):.2%}")
    lines.append(f"- 检测框数量：{int(aggregate.get('detection_count') or 0)}")
    if overlay_urls:
        lines.append(f"- 灾害区域叠加图：{overlay_urls[0]}")
    if detection_urls:
        lines.append(f"- 物体检测标注图：{detection_urls[0]}")

    top_detections: list[dict[str, Any]] = []
    for image in images:
        top_detections.extend(image.get("detections") or [])
    top_detections.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
    if top_detections:
        lines.append("- Top 检测结果：")
        for item in top_detections[:5]:
            bbox = item.get("bbox") or []
            lines.append(
                f"  - {item.get('class_name') or item.get('label')} "
                f"conf={float(item.get('confidence') or 0):.2f}, bbox={bbox}"
            )

    return "\n".join(lines)


class AgentSessionStore:
    """In-memory session store keyed by task_id."""

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
    return list(iter_agent_events(task_id, user_id, message, files, params))


def iter_agent_events(
    task_id: int,
    user_id: int,
    message: str,
    files: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    metadata = session_store.metadata_for(task_id)
    params = dict(params or {})

    pending_request = metadata.get("pending_report_request")
    selected_format = _parse_report_format(message)
    if pending_request and selected_format:
        params = {
            **pending_request.get("params", {}),
            **params,
            "forced_tool": pending_request.get("forced_tool", "disaster_analysis"),
            "report_format": selected_format,
            "format": selected_format,
            "auto_confirm_memory": True,
            "capture_screenshot": True,
        }
        message = pending_request.get("message") or message
        metadata.pop("pending_report_request", None)

    forced_tool = str(params.get("forced_tool") or "")
    needs_report_format = forced_tool in {"disaster_analysis", "task_draft", "report"}
    if needs_report_format and not (params.get("report_format") or params.get("format")):
        metadata["pending_report_request"] = {
            "message": message,
            "params": params,
            "forced_tool": forced_tool,
        }
        yield {
            "type": "report_format_required",
            "content": "生成灾害分析报告前，请选择导出格式：Word 还是 PDF？",
            "data": {"choices": [{"label": "Word", "format": "docx"}, {"label": "PDF", "format": "pdf"}]},
        }
        yield {"type": "answer", "content": "请选择报告格式：**Word** 或 **PDF**。"}
        yield {"type": "done", "content": "等待报告格式选择", "session": metadata}
        return

    if needs_report_format:
        params.setdefault("auto_confirm_memory", True)
        params.setdefault("capture_screenshot", True)
        params.setdefault("format", params.get("report_format", "docx"))

    context = ToolContext(task_id=task_id, user_id=user_id, metadata=metadata)
    tool_input = ToolInput(query=message, files=files or [], params=params)

    if tool_input.params.get("conversation_history"):
        metadata["conversation_history"] = tool_input.params["conversation_history"]
    if tool_input.params.get("conversation_record"):
        metadata["conversation_record"] = tool_input.params["conversation_record"]

    yield {"type": "thinking", "content": "正在识别意图并规划工具调用..."}
    router_result = IntentRouterTool().run(tool_input, context)
    tools_to_run = router_result.data.get("tools", [])
    yield {"type": "intent", "content": router_result.summary, "data": router_result.data}

    results: dict[str, ToolResult] = {}
    for tool_name in tools_to_run:
        yield {"type": "tool_call", "tool": tool_name, "content": f"正在调用工具：{tool_name}"}
        try:
            result = call_tool(tool_name, tool_input, context)
            results[tool_name] = result
            _update_session_from_result(tool_name, result, metadata)
            yield _tool_result_event(tool_name, result)
        except Exception as error:
            yield {
                "type": "tool_result",
                "tool": tool_name,
                "content": f"工具调用失败：{error}",
                "error": str(error),
            }

    yield {"type": "llm_call", "content": "正在调用 LLM 整合对话记录、相关文档、联网结果与报告产物..."}
    answer = ""
    try:
        for chunk in stream_llm_answer(message, results, metadata):
            answer += chunk
            yield {"type": "answer_delta", "content": chunk}
    except Exception as error:
        answer = synthesize_answer(message, results, metadata)
        yield {
            "type": "llm_fallback",
            "content": f"LLM 调用失败，已降级为工具摘要：{error}",
            "error": str(error),
        }
        for chunk in _chunk_text(answer):
            time.sleep(0.03)
            yield {"type": "answer_delta", "content": chunk}

    if not answer:
        answer = synthesize_answer(message, results, metadata)
        for chunk in _chunk_text(answer):
            time.sleep(0.03)
            yield {"type": "answer_delta", "content": chunk}

    image_appendix = _image_result_appendix(results)
    if image_appendix and image_appendix not in answer:
        answer += image_appendix
        for chunk in _chunk_text(image_appendix):
            time.sleep(0.03)
            yield {"type": "answer_delta", "content": chunk}

    yield {"type": "answer", "content": answer}
    yield {"type": "done", "content": "完成", "session": metadata}


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

    if tool_name == "memory":
        if "draft" not in params and metadata.get("last_draft"):
            params["draft"] = metadata["last_draft"]
        if params.get("auto_confirm_memory"):
            params["confirmed"] = True
    if tool_name == "graphrag" and "documents" not in params and metadata.get("documents"):
        params["documents"] = metadata["documents"]
    if tool_name == "risk_assessment" and "formal_memory" not in params and metadata.get("formal_memory"):
        params["formal_memory"] = metadata["formal_memory"]
    if tool_name == "report":
        params.setdefault("format", params.get("report_format", "docx"))
        if metadata.get("formal_memory") and "task" not in params:
            params["task"] = metadata["formal_memory"]
        if metadata.get("risk_assessment") and "risk_assessment" not in params:
            params["risk_assessment"] = metadata["risk_assessment"]
        if metadata.get("documents") and "documents" not in params:
            params["documents"] = metadata["documents"]
        if metadata.get("evidence") and "evidence" not in params:
            params["evidence"] = metadata["evidence"]
        if metadata.get("artifacts") and "artifacts" not in params:
            params["artifacts"] = metadata["artifacts"]
        if metadata.get("conversation_record") and "summary" not in params:
            params["summary"] = metadata["conversation_record"]
    if tool_name == "email":
        if metadata.get("last_report_path") and "report_path" not in params:
            params["report_path"] = metadata["last_report_path"]
        if metadata.get("last_report_path") and "attachments" not in params:
            params["attachments"] = [metadata["last_report_path"]]

    return ToolInput(query=tool_input.query, files=tool_input.files, params=params)


def _update_session_from_result(
    tool_name: str,
    result: ToolResult,
    metadata: dict[str, Any],
) -> None:
    if result.evidence:
        metadata.setdefault("evidence", []).extend(item.__dict__ for item in result.evidence)
    if result.artifacts:
        metadata.setdefault("artifacts", []).extend(item.__dict__ for item in result.artifacts)
    if tool_name == "task_draft" and result.data.get("draft"):
        metadata["last_draft"] = result.data["draft"]
    if tool_name == "document" and result.data.get("documents"):
        metadata["documents"] = result.data["documents"]
    if tool_name == "memory" and result.data.get("formal_memory"):
        metadata["formal_memory"] = result.data["formal_memory"]
        metadata["confirmed_task"] = True
    if tool_name == "risk_assessment" and result.data.get("assessment"):
        metadata["risk_assessment"] = result.data["assessment"]
    if tool_name == "report" and result.data.get("report_path"):
        metadata["last_report_path"] = result.data["report_path"]


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


def synthesize_answer(
    message: str,
    results: dict[str, ToolResult],
    metadata: dict[str, Any] | None = None,
) -> str:
    history = (metadata or {}).get("conversation_history") or []
    if not results:
        remembered_name = _extract_name_from_history(history)
        if remembered_name and any(word in message for word in ("我是谁", "我叫什么", "我的名字")):
            return f"你是{remembered_name}。"
        return "我收到了。当前未调用工具；我会结合本任务内的历史对话继续回答。"

    lines = ["本轮已完成以下工具调用："]
    for tool_name, result in results.items():
        lines.append(f"- **{tool_name}**：{result.summary}")
    return "\n".join(lines)


def _parse_report_format(message: str) -> str | None:
    normalized = message.strip().lower()
    if any(word in normalized for word in ("word", "docx", "文档")):
        return "docx"
    if any(word in normalized for word in ("pdf",)):
        return "pdf"
    return None


def _extract_name_from_history(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        content = str(item.get("content") or "")
        if "我是" in content:
            return content.split("我是", 1)[1].strip().split()[0][:20]
    return None
