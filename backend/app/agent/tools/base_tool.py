"""工具基类：所有 Agent 工具必须继承此类并实现 run()。"""
from abc import ABC, abstractmethod


class BaseTool(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, query: str) -> str:
        """执行工具逻辑，返回文本结果。"""
        ...
