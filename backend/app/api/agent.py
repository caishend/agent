"""Agent 后端接口。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.agent.runtime import call_tool, confirm_task_draft, iter_agent_events, run_agent_once, session_store
from app.agent.tools.base_tool import ToolContext, ToolInput
from app.api.overview import sync_event_from_agent_session
from app.db import SessionLocal, get_db
from app.models.conversation import Conversation, Document
from app.models.task import Task
from app.utils import get_current_user_id

router = APIRouter()


class AgentMessageIn(BaseModel):
    message: str
    files: list[dict[str, Any]] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ConfirmDraftIn(BaseModel):
    draft: dict[str, Any]
    selected_fields: list[str] | None = None


class ToolRunIn(BaseModel):
    query: str
    files: list[dict[str, Any]] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ConversationRecordIn(BaseModel):
    content: str = ""


@router.post("/{task_id}/agent/message")
def run_agent_message(
    task_id: int,
    data: AgentMessageIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _get_task_or_404(task_id, user_id, db)
    files = _with_uploaded_documents(db, task_id, data.files)
    _save_message(db, task_id, "user", data.message)
    params = _with_conversation_history(db, task_id, data.params)
    events = run_agent_once(
        task_id=task_id,
        user_id=user_id,
        message=data.message,
        files=files,
        params=params,
    )
    answer = _last_answer(events)
    if answer:
        _save_message(db, task_id, "assistant", answer)
        sync_event_from_agent_session(db, task_id, session_store.metadata_for(task_id))
    return {
        "task_id": task_id,
        "events": events,
        "answer": answer,
        "session": session_store.metadata_for(task_id),
    }


@router.post("/{task_id}/agent/stream")
def stream_agent_message(
    task_id: int,
    data: AgentMessageIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _get_task_or_404(task_id, user_id, db)
    files = _with_uploaded_documents(db, task_id, data.files)
    _save_message(db, task_id, "user", data.message)
    params = _with_conversation_history(db, task_id, data.params)
    assistant_conv_id = _save_message(db, task_id, "assistant", "正在生成回复...")

    def event_stream():
        answer_chunks: list[str] = []
        answer_saved = False
        done_sent = False
        last_persisted_length = 0
        trace = _new_trace_record(data.message)
        trace_row = _create_tool_record(db, task_id, trace)

        def current_answer() -> str:
            return "".join(answer_chunks).strip()

        def persist(content: str, *, force: bool = False) -> None:
            nonlocal last_persisted_length
            if force or len(content) - last_persisted_length >= 240:
                _update_message_in_new_session(assistant_conv_id, content or "正在生成回复...")
                last_persisted_length = len(content)

        try:
            yield ": connected\r\n\r\n"
            for event in iter_agent_events(
                task_id=task_id,
                user_id=user_id,
                message=data.message,
                files=files,
                params=params,
            ):
                _append_trace_event(trace, event)
                _update_tool_record(db, trace_row, trace)
                if event.get("type") == "answer_delta":
                    answer_chunks.append(str(event.get("content") or ""))
                    persist(current_answer())
                if event.get("type") == "answer":
                    answer = str(event.get("content") or "")
                    if answer:
                        _update_message_in_new_session(assistant_conv_id, answer)
                        last_persisted_length = len(answer)
                        answer_saved = True
                if event.get("type") == "done":
                    done_sent = True
                if event.get("type") == "tool_result" and event.get("tool") == "report":
                    _register_report_artifacts(db, task_id, event.get("artifacts") or [])
                yield _sse_data(event)
            if not done_sent:
                yield _sse_data({"type": "done", "content": "完成", "session": session_store.metadata_for(task_id)})
            final_answer = current_answer()
            if final_answer or answer_saved:
                _update_tool_record(db, trace_row, trace)
                if final_answer and not answer_saved:
                    _update_message_in_new_session(assistant_conv_id, final_answer)
                sync_event_from_agent_session(db, task_id, session_store.metadata_for(task_id))
        except Exception as error:
            if not answer_saved:
                fallback = current_answer() or f"调用失败：{error}"
                _update_message_in_new_session(assistant_conv_id, fallback)
            payload = {"type": "error", "content": str(error), "error": str(error)}
            _append_trace_event(trace, payload)
            _update_tool_record(db, trace_row, trace)
            yield _sse_data(payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{task_id}/agent/confirm-draft")
def confirm_agent_draft(
    task_id: int,
    data: ConfirmDraftIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _get_task_or_404(task_id, user_id, db)
    result = confirm_task_draft(
        task_id=task_id,
        user_id=user_id,
        draft=data.draft,
        selected_fields=data.selected_fields,
    )
    _save_message(db, task_id, "assistant", "已确认并写入正式任务记忆。")
    return result.to_dict()


@router.get("/{task_id}/agent/session")
def get_agent_session(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _get_task_or_404(task_id, user_id, db)
    metadata = session_store.metadata_for(task_id)
    metadata.setdefault("conversation_record", _load_conversation_record(db, task_id))
    return {"task_id": task_id, "session": metadata}


@router.post("/{task_id}/agent/record")
def save_conversation_record(
    task_id: int,
    data: ConversationRecordIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _get_task_or_404(task_id, user_id, db)
    content = data.content.strip()
    _save_tool_record(db, task_id, {"kind": "conversation_record", "content": content})
    session_store.metadata_for(task_id)["conversation_record"] = content
    return {"task_id": task_id, "conversation_record": content}


@router.delete("/{task_id}/agent/session", status_code=204)
def clear_agent_session(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _get_task_or_404(task_id, user_id, db)
    session_store.clear(task_id)
    db.query(Conversation).filter(Conversation.task_id == task_id).delete()
    db.commit()


@router.post("/{task_id}/tools/{tool_name}")
def run_tool(
    task_id: int,
    tool_name: str,
    data: ToolRunIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _get_task_or_404(task_id, user_id, db)
    context = ToolContext(
        task_id=task_id,
        user_id=user_id,
        metadata=session_store.metadata_for(task_id),
    )
    try:
        result = call_tool(
            tool_name,
            ToolInput(query=data.query, files=data.files, params=data.params),
            context,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return result.to_dict()


def _get_task_or_404(task_id: int, user_id: int, db: Session) -> Task:
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _save_message(db: Session, task_id: int, role: str, content: str) -> int:
    row = Conversation(task_id=task_id, role=role, content=content)
    db.add(row)
    db.commit()
    db.refresh(row)
    return int(row.conv_id)


def _update_message_in_new_session(conv_id: int, content: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(Conversation).filter(Conversation.conv_id == conv_id).first()
        if not row:
            return
        row.content = content
        db.commit()
    finally:
        db.close()


def _register_report_artifacts(db: Session, task_id: int, artifacts: list[dict[str, Any]]) -> None:
    for artifact in artifacts:
        if artifact.get("type") != "report":
            continue
        path = str(artifact.get("path") or "")
        if not path:
            continue
        filename = Path(path).name
        file_type = Path(path).suffix.lower().lstrip(".").upper() or "REPORT"
        exists = db.query(Document).filter(Document.task_id == task_id, Document.file_path == path).first()
        if exists:
            continue
        db.add(Document(task_id=task_id, filename=filename, file_type=file_type, file_path=path))
    db.commit()


def _create_tool_record(db: Session, task_id: int, payload: dict[str, Any]) -> Conversation:
    row = Conversation(task_id=task_id, role="tool", content=json.dumps(_compact_trace_payload(payload), ensure_ascii=False, default=str))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _update_tool_record(db: Session, row: Conversation, payload: dict[str, Any]) -> None:
    try:
        row.content = json.dumps(_compact_trace_payload(payload), ensure_ascii=False, default=str)
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()


def _save_tool_record(db: Session, task_id: int, payload: dict[str, Any]) -> None:
    kind = payload.get("kind")
    if kind == "conversation_record":
        existing_rows = (
            db.query(Conversation)
            .filter(Conversation.task_id == task_id, Conversation.role == "tool")
            .order_by(Conversation.created_at.desc(), Conversation.conv_id.desc())
            .all()
        )
        for row in existing_rows:
            try:
                if json.loads(row.content or "{}").get("kind") == "conversation_record":
                    row.content = json.dumps(_compact_trace_payload(payload), ensure_ascii=False, default=str)
                    db.commit()
                    return
            except json.JSONDecodeError:
                continue
    _save_message(db, task_id, "tool", json.dumps(_compact_trace_payload(payload), ensure_ascii=False, default=str))


def _compact_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("kind") != "agent_trace":
        return payload

    progress = [str(item)[:600] for item in (payload.get("progress") or []) if str(item).strip()]
    artifacts = payload.get("artifacts") or []
    search_results = []
    for item in (payload.get("searchResults") or [])[:10]:
        if not isinstance(item, dict):
            continue
        search_results.append(
            {
                "title": str(item.get("title") or item.get("name") or "")[:180],
                "url": item.get("url"),
                "content": str(item.get("content") or item.get("snippet") or item.get("summary") or "")[:500],
            }
        )

    compact = {
        "kind": "agent_trace",
        "requestText": str(payload.get("requestText") or "")[:1000],
        "progress": progress[-80:],
        "searchResults": search_results,
        "artifacts": artifacts[-20:] if isinstance(artifacts, list) else [],
        "data": _summarize_trace_data(payload.get("data")),
    }
    return compact


def _summarize_trace_data(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    summary_keys = (
        "search_mode",
        "query",
        "graph_status",
        "entity_count",
        "relation_count",
        "risk_level",
        "risk_score",
        "report_path",
        "document_mode",
    )
    summary = {key: data.get(key) for key in summary_keys if key in data}
    if data.get("screenshot_observations"):
        summary["screenshot_observations"] = [str(item)[:500] for item in data.get("screenshot_observations", [])[:10]]
    if data.get("draft"):
        summary["draft"] = data.get("draft")
    return summary or None


def _load_conversation_record(db: Session, task_id: int) -> str:
    rows = (
        db.query(Conversation)
        .filter(Conversation.task_id == task_id, Conversation.role == "tool")
        .order_by(Conversation.created_at.desc(), Conversation.conv_id.desc())
        .all()
    )
    for row in rows:
        try:
            payload = json.loads(row.content or "{}")
        except json.JSONDecodeError:
            continue
        if payload.get("kind") == "conversation_record":
            return str(payload.get("content") or "")
    return ""


def _with_conversation_history(db: Session, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(params or {})
    rows = (
        db.query(Conversation)
        .filter(Conversation.task_id == task_id, Conversation.role.in_(["user", "assistant"]))
        .order_by(Conversation.created_at.desc(), Conversation.conv_id.desc())
        .limit(12)
        .all()
    )
    enriched["conversation_history"] = [
        {
            "role": row.role,
            "content": row.content,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in reversed(rows)
    ]
    return enriched


def _with_uploaded_documents(db: Session, task_id: int, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(files or [])
    seen_paths = {str(item.get("path") or item.get("file_path") or "") for item in merged}
    rows = db.query(Document).filter(Document.task_id == task_id).order_by(Document.upload_time.desc()).all()
    for row in rows:
        if row.file_path in seen_paths:
            continue
        merged.append(
            {
                "path": row.file_path,
                "name": row.filename,
                "filename": row.filename,
                "type": row.file_type,
                "doc_id": row.doc_id,
            }
        )
    return merged


def _last_answer(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "answer":
            return str(event.get("content") or "")
    return ""


def _sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\r\n\r\n"


def _new_trace_record(message: str) -> dict[str, Any]:
    return {
        "kind": "agent_trace",
        "requestText": message,
        "progress": ["请求已发送，等待后端开始流式响应..."],
        "searchResults": [],
        "artifacts": [],
        "data": None,
    }


def _append_trace_event(trace: dict[str, Any], event: dict[str, Any]) -> None:
    event_type = event.get("type")
    content = str(event.get("content") or "").strip()
    if event_type in {"thinking", "intent", "tool_call", "tool_result", "llm_call", "llm_fallback", "error"} and content:
        trace.setdefault("progress", []).append(content)

    if event_type == "tool_result":
        tool_name = event.get("tool") or "tool"
        trace.setdefault("progress", []).append(f"工具 {tool_name} 已完成")
        if event.get("data"):
            trace["data"] = event.get("data")
        if tool_name == "browser" and isinstance(event.get("data"), dict):
            search_results = event["data"].get("search_results") or []
            if search_results:
                trace["searchResults"] = search_results
            screenshot_observations = event["data"].get("screenshot_observations") or []
            trace.setdefault("progress", []).extend(str(item) for item in screenshot_observations)

    if event.get("artifacts"):
        trace.setdefault("artifacts", []).extend(event.get("artifacts") or [])
