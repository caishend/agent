"""Agent 工具基类与统一返回结构。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolInput:
    query: str
    files: list[dict[str, Any]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    task_id: int | None = None
    user_id: int | None = None
    conversation_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceItem:
    source: str
    type: str
    content: str
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactItem:
    type: str
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    summary: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    artifacts: list[ArtifactItem] = field(default_factory=list)
    confidence: float | None = None
    need_user_confirm: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        lines = [self.summary]
        if self.confidence is not None:
            lines.append(f"可信度：{self.confidence:.2f}")
        if self.need_user_confirm:
            lines.append("需要用户确认后再写入正式任务记忆。")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "evidence": [asdict(item) for item in self.evidence],
            "artifacts": [asdict(item) for item in self.artifacts],
            "confidence": self.confidence,
            "need_user_confirm": self.need_user_confirm,
            "data": self.data,
        }


class BaseTool(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        """执行工具逻辑，返回结构化结果。"""
        ...
