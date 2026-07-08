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
from app.db import get_db
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

    def event_stream():
        answer = ""
        try:
            for event in iter_agent_events(
                task_id=task_id,
                user_id=user_id,
                message=data.message,
                files=data.files,
                params=params,
            ):
                if event.get("type") == "answer":
                    answer = str(event.get("content") or "")
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            if answer:
                _save_message(db, task_id, "assistant", answer)
        except Exception as error:
            payload = {"type": "error", "content": str(error), "error": str(error)}
            yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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


def _save_message(db: Session, task_id: int, role: str, content: str) -> None:
    db.add(Conversation(task_id=task_id, role=role, content=content))
    db.commit()


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
