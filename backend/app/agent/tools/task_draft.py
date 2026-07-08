"""临时任务草稿工具。"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from app.agent.tools.base_tool import BaseTool, ToolContext, ToolInput, ToolResult


class TaskDraftTool(BaseTool):
    name = "task_draft"
    description = "基于本轮对话整理临时任务草稿，等待用户确认哪些信息需要保留。"

    disaster_patterns = (
        ("暴雨洪涝", ("暴雨洪涝", "洪涝", "洪水", "内涝", "暴雨")),
        ("台风", ("台风", "强风", "风暴潮")),
        ("地震", ("地震", "震中", "余震")),
        ("滑坡泥石流", ("滑坡", "泥石流", "山体滑坡")),
        ("火灾", ("火灾", "山火", "森林火灾")),
        ("干旱", ("干旱", "缺水")),
    )
    known_locations = (
        "北京",
        "上海",
        "广州",
        "深圳",
        "成都",
        "重庆",
        "武汉",
        "杭州",
        "南京",
        "郑州",
        "西安",
        "天津",
        "福州",
        "厦门",
        "长沙",
        "南昌",
        "哈尔滨",
        "长春",
        "沈阳",
        "石家庄",
        "昆明",
        "贵阳",
        "南宁",
        "海口",
        "兰州",
        "西宁",
        "银川",
        "乌鲁木齐",
        "拉萨",
        "青岛",
        "苏州",
        "宁波",
    )
    time_keywords = (
        "今天",
        "昨日",
        "昨天",
        "明天",
        "当前",
        "现在",
        "近期",
        "本周",
        "未来24小时",
        "未来48小时",
        "未来72小时",
    )

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        query = tool_input.query.strip()
        disaster_type = self._extract_disaster_type(query)
        locations = self._extract_locations(query)
        time_range = self._extract_time_range(query)
        candidate_evidence = self._normalize_evidence(
            tool_input.params.get("candidate_evidence", [])
        )
        missing_info = self._find_missing_info(disaster_type, locations, time_range)

        draft = {
            "status": "pending_user_confirmation",
            "title": self._build_title(disaster_type, locations, time_range),
            "disaster_type": disaster_type,
            "locations": locations,
            "time_range": time_range,
            "known_info": self._build_known_info(disaster_type, locations, time_range),
            "missing_info": missing_info,
            "candidate_evidence": candidate_evidence,
            "source_message": query,
            "context": {
                "task_id": context.task_id if context else None,
                "user_id": context.user_id if context else None,
                "conversation_id": context.conversation_id if context else None,
            },
        }

        return ToolResult(
            summary=self._build_summary(draft),
            need_user_confirm=True,
            confidence=self._estimate_confidence(missing_info),
            data={"draft": draft},
        )

    def _extract_disaster_type(self, query: str) -> str:
        normalized_query = query.lower()
        for disaster_type, keywords in self.disaster_patterns:
            if any(keyword.lower() in normalized_query for keyword in keywords):
                return disaster_type
        return "未知"

    def _extract_locations(self, query: str) -> list[str]:
        return [location for location in self.known_locations if location in query]

    def _extract_time_range(self, query: str) -> str:
        for keyword in self.time_keywords:
            if keyword in query:
                return keyword
        return "未知"

    def _find_missing_info(
        self,
        disaster_type: str,
        locations: list[str],
        time_range: str,
    ) -> list[str]:
        missing_info = []
        if disaster_type == "未知":
            missing_info.append("灾害类型")
        if not locations:
            missing_info.append("影响区域")
        if time_range == "未知":
            missing_info.append("时间范围")
        missing_info.extend(["受影响人口/设施", "已有证据来源"])
        return missing_info

    def _build_known_info(
        self,
        disaster_type: str,
        locations: list[str],
        time_range: str,
    ) -> list[dict[str, Any]]:
        known_info = []
        if disaster_type != "未知":
            known_info.append({"field": "灾害类型", "value": disaster_type})
        if locations:
            known_info.append({"field": "影响区域", "value": locations})
        if time_range != "未知":
            known_info.append({"field": "时间范围", "value": time_range})
        return known_info

    def _normalize_evidence(self, candidate_evidence: list[Any]) -> list[dict[str, Any]]:
        normalized = []
        for item in candidate_evidence:
            if is_dataclass(item):
                normalized.append(asdict(item))
            elif isinstance(item, dict):
                normalized.append(item)
            else:
                normalized.append({"source": "unknown", "type": "text", "content": str(item)})
        return normalized

    def _build_title(
        self,
        disaster_type: str,
        locations: list[str],
        time_range: str,
    ) -> str:
        location_text = "、".join(locations) if locations else "待确认区域"
        disaster_text = disaster_type if disaster_type != "未知" else "待确认灾害"
        time_text = time_range if time_range != "未知" else "待确认时间"
        return f"{location_text}{time_text}{disaster_text}分析任务草稿"

    def _build_summary(self, draft: dict[str, Any]) -> str:
        missing_text = "、".join(draft["missing_info"]) if draft["missing_info"] else "无"
        return (
            f"已生成临时任务草稿：{draft['title']}。"
            f"请确认需要保留的信息；仍缺少：{missing_text}。"
            "确认前不会写入正式任务记忆。"
        )

    def _estimate_confidence(self, missing_info: list[str]) -> float:
        base_confidence = 0.82
        return max(0.45, base_confidence - len(missing_info) * 0.06)
