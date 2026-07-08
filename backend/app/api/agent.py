"""Agent 后端接口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.runtime import call_tool, confirm_task_draft, run_agent_once, session_store
from app.agent.tools.base_tool import ToolContext, ToolInput
from app.db import get_db
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
    events = run_agent_once(
        task_id=task_id,
        user_id=user_id,
        message=data.message,
        files=data.files,
        params=data.params,
    )
    return {
        "task_id": task_id,
        "events": events,
        "answer": events[-1]["content"] if events else "",
        "session": session_store.metadata_for(task_id),
    }


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
