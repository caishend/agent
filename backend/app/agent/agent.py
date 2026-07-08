"""Agent 主入口：兼容旧 SSE 接口。"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.agent.runtime import run_agent_once


def run_agent(task_id: int, message: str, db: Session) -> Generator[dict, None, None]:
    """流式运行 Agent，供旧版 `/chat` SSE 接口使用。"""
    events = run_agent_once(task_id=task_id, user_id=0, message=message)
    for event in events:
        yield event
