from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db import get_db
from app.models.task import Task
from app.models.conversation import Conversation
from app.utils import get_current_user_id
from app.agent.agent import run_agent
import json

router = APIRouter()

class ChatIn(BaseModel):
    message: str

@router.get("/{task_id}/chat")
def get_history(task_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return db.query(Conversation).filter(Conversation.task_id == task_id).order_by(Conversation.created_at).all()

@router.post("/{task_id}/chat")
def chat(task_id: int, data: ChatIn,
         user_id: int = Depends(get_current_user_id),
         db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")

    # 保存用户消息
    db.add(Conversation(task_id=task_id, role="user", content=data.message))
    db.commit()

    # SSE 流式返回
    def event_stream():
        full_response = ""
        for chunk in run_agent(task_id=task_id, message=data.message, db=db):
            full_response += chunk.get("content", "")
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        # 保存 assistant 消息
        db.add(Conversation(task_id=task_id, role="assistant", content=full_response))
        db.commit()
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
