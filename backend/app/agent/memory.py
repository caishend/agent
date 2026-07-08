"""
任务记忆管理：维护每个 Task 的动态上下文（已知信息、分析结果、工具产出）。
"""
import json
from sqlalchemy.orm import Session


class TaskMemory:
    def __init__(self, task_id: int, db: Session):
        self.task_id = task_id
        self.db = db
        self._data: dict = self._load()

    def _load(self) -> dict:
        """从数据库加载任务知识（task_document 表，占位用内存实现）。"""
        return {
            "task_id": self.task_id,
            "known_info": [],
            "tool_results": {},
            "risk_level": None,
            "suggestion": None
        }

    def update(self, key: str, value):
        """更新任务记忆中的某个字段。"""
        self._data["tool_results"][key] = value

    def get(self, key: str):
        return self._data.get(key)

    def to_context_str(self) -> str:
        """将当前记忆序列化为供 LLM 阅读的上下文字符串。"""
        return json.dumps(self._data, ensure_ascii=False, indent=2)
