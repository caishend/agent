from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.db import get_db
from app.models.task import Task
from app.utils import get_current_user_id

router = APIRouter()

class TaskIn(BaseModel):
    task_name: str
    disaster_type: Optional[str] = None
    location: Optional[str] = None

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
