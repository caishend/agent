"""Agent 后端接口。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.agent.runtime import call_tool, confirm_task_draft, iter_agent_events, run_agent_once, session_store
from app.agent.tools.base_tool import ToolContext, ToolInput
from app.db import SessionLocal, get_db
from app.models.conversation import Conversation
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


@router.post("/{task_id}/agent/message")
def run_agent_message(
    task_id: int,
    data: AgentMessageIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _get_task_or_404(task_id, user_id, db)
    _save_message(db, task_id, "user", data.message)
    params = _with_conversation_history(db, task_id, data.params)
    events = run_agent_once(
        task_id=task_id,
        user_id=user_id,
        message=data.message,
        files=data.files,
        params=params,
    )
    answer = _last_answer(events)
    if answer:
        _save_message(db, task_id, "assistant", answer)
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
    _save_message(db, task_id, "user", data.message)
    params = _with_conversation_history(db, task_id, data.params)
    assistant_conv_id = _save_message(db, task_id, "assistant", "正在生成回复...")

    def event_stream():
        answer_chunks: list[str] = []
        answer_saved = False
        done_sent = False
        last_persisted_length = 0

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
                files=data.files,
                params=params,
            ):
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
                yield _sse_data(event)
            if not done_sent:
                yield _sse_data({"type": "done", "content": "完成", "session": session_store.metadata_for(task_id)})
        except Exception as error:
            if not answer_saved:
                fallback = current_answer() or f"调用失败：{error}"
                _update_message_in_new_session(assistant_conv_id, fallback)
            payload = {"type": "error", "content": str(error), "error": str(error)}
            yield _sse_data(payload)
        finally:
            if not answer_saved:
                partial = current_answer()
                if partial:
                    _update_message_in_new_session(assistant_conv_id, partial)

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
    return {"task_id": task_id, "session": session_store.metadata_for(task_id)}


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
    last_error: Exception | None = None
    for candidate in _content_candidates(content):
        row = Conversation(task_id=task_id, role=role, content=candidate)
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            return int(row.conv_id)
        except Exception as error:
            db.rollback()
            last_error = error
    if last_error:
        raise last_error
    raise ValueError("message content cannot be saved")


def _save_message_in_new_session(task_id: int, role: str, content: str) -> None:
    db = SessionLocal()
    try:
        _save_message(db, task_id, role, content)
    finally:
        db.close()


def _update_message_in_new_session(conv_id: int, content: str) -> None:
    db = SessionLocal()
    try:
        _update_message(db, conv_id, content)
    finally:
        db.close()


def _update_message(db: Session, conv_id: int, content: str) -> None:
    last_error: Exception | None = None
    for candidate in _content_candidates(content):
        row = db.query(Conversation).filter(Conversation.conv_id == conv_id).first()
        if not row:
            return
        row.content = candidate
        try:
            db.commit()
            return
        except Exception as error:
            db.rollback()
            last_error = error
    if last_error:
        raise last_error


def _content_candidates(content: str) -> list[str]:
    normalized = str(content or "").replace("\x00", "")
    stripped = "".join(char for char in normalized if ord(char) <= 0xFFFF)
    candidates = [normalized]
    if stripped != normalized:
        candidates.append(stripped)
    return candidates


def _with_conversation_history(db: Session, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(params or {})
    rows = (
        db.query(Conversation)
        .filter(Conversation.task_id == task_id)
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


def _last_answer(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "answer":
            return str(event.get("content") or "")
    return ""


def _sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\r\n\r\n"
