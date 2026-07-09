import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.agent import run_agent
from app.db import get_db
from app.models.conversation import Conversation
from app.models.task import Task
from app.utils import get_current_user_id

router = APIRouter()


class ChatIn(BaseModel):
    message: str


@router.get("/{task_id}/chat")
def get_history(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return (
        db.query(Conversation)
        .filter(Conversation.task_id == task_id)
        .order_by(Conversation.created_at, Conversation.conv_id)
        .all()
    )


@router.post("/{task_id}/chat")
def chat(
    task_id: int,
    data: ChatIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")

    db.add(Conversation(task_id=task_id, role="user", content=data.message))
    db.commit()

    def event_stream():
        full_response = ""
        yield ": connected\r\n\r\n"
        for chunk in run_agent(task_id=task_id, message=data.message, db=db):
            full_response += chunk.get("content", "")
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\r\n\r\n"
        db.add(Conversation(task_id=task_id, role="assistant", content=full_response))
        db.commit()
        yield 'data: {"type":"done"}\r\n\r\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
