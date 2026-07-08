from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.email import EmailTool
from app.db import get_db
from app.models.task import Task
from app.utils import get_current_user_id

router = APIRouter()

class TaskIn(BaseModel):
    task_name: str
    disaster_type: Optional[str] = None
    location: Optional[str] = None

class SendReportIn(BaseModel):
    recipients: str | list[str]
    subject: Optional[str] = None
    body: Optional[str] = None
    attachments: list[str] = Field(default_factory=list)
    report_path: Optional[str] = None
    cc: str | list[str] | None = None
    bcc: str | list[str] | None = None

@router.get("")
def list_tasks(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.query(Task).filter(Task.user_id == user_id).order_by(Task.create_time.desc()).all()

@router.post("", status_code=201)
def create_task(data: TaskIn, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    task = Task(**data.model_dump(), user_id=user_id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

@router.get("/{task_id}")
def get_task(task_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return task

@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    db.delete(task)
    db.commit()

@router.post("/{task_id}/report/send")
def send_report(task_id: int, data: SendReportIn,
                user_id: int = Depends(get_current_user_id),
                db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")

    params = data.model_dump(exclude_none=True)
    query = data.body or f"发送任务 {task_id} 的 SkyGuard 灾害分析报告"
    result = EmailTool().run(
        ToolInput(query=query, params=params),
        ToolContext(task_id=task_id, user_id=user_id),
    )
    return result.to_dict()
