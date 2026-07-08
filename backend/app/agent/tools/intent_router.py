"""用户意图识别与工具规划工具。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.tools.base_tool import BaseTool, ToolContext, ToolInput, ToolResult


class IntentRouterTool(BaseTool):
    name = "intent_router"
    description = "识别用户意图，并给出本轮对话建议调用的工具列表。"

    hazard_keywords = (
        "灾害",
        "洪涝",
        "洪水",
        "暴雨",
        "台风",
        "地震",
        "滑坡",
        "泥石流",
        "火灾",
        "干旱",
        "内涝",
    )
    disaster_action_keywords = (
        "灾害分析",
        "分析灾害",
        "风险",
        "评估",
        "应急",
        "预案",
        "灾情",
        "受灾",
        "创建任务",
        "建立任务",
        "形成任务",
    )
    realtime_keywords = (
        "最新",
        "实时",
        "今天",
        "现在",
        "新闻",
        "搜索",
        "预警",
        "公告",
        "网页",
        "浏览器",
        "网上",
    )
    screenshot_keywords = ("截图", "截屏", "页面图", "网页图")
    remote_sensing_keywords = (
        "遥感",
        "卫星",
        "影像",
        "淹没",
        "水体",
        "ndvi",
        "ndwi",
        "sar",
        "tif",
        "tiff",
    )
    document_keywords = (
        "文档",
        "资料",
        "pdf",
        "word",
        "docx",
        "excel",
        "表格",
        "上传",
        "文件",
        "报告内容",
    )
    report_keywords = ("报告", "生成文档", "导出", "pdf")
    email_keywords = ("邮件", "通知", "发送", "抄送")
    knowledge_keywords = ("为什么", "原因", "机制", "措施", "怎么", "如何", "解释")
    assessment_keywords = ("开始评估", "风险评估", "进行评估", "开始分析", "正式分析")
    confirmation_keywords = ("已确认", "确认", "保留这些", "就这些", "可以开始")

    image_extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
    document_extensions = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".md"}

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        query = tool_input.query.strip()
        normalized_query = query.lower()
        params = tool_input.params or {}

        file_profile = self._profile_files(tool_input.files)
        has_confirmed_task = self._has_confirmed_task(params, context, normalized_query)

        signals = {
            "hazard_topic": self._contains_any(normalized_query, self.hazard_keywords),
            "disaster": self._is_disaster_analysis_intent(normalized_query),
            "realtime": self._contains_any(normalized_query, self.realtime_keywords),
            "screenshot": self._contains_any(normalized_query, self.screenshot_keywords),
            "remote_sensing": self._contains_any(normalized_query, self.remote_sensing_keywords)
            or file_profile["has_image"],
            "document": self._contains_any(normalized_query, self.document_keywords)
            or file_profile["has_document"],
            "report": self._contains_any(normalized_query, self.report_keywords),
            "email": self._contains_any(normalized_query, self.email_keywords),
            "knowledge": self._contains_any(normalized_query, self.knowledge_keywords),
            "assessment": self._contains_any(normalized_query, self.assessment_keywords),
        }

        intents: list[str] = []
        tools: list[str] = []
        next_step = "answer"
        need_user_confirm = False

        if signals["realtime"]:
            intents.append("realtime_search")
            tools.append("browser")
        if signals["screenshot"]:
            intents.append("browser_screenshot")
            tools.append("browser")
        if signals["remote_sensing"]:
            intents.append("remote_sensing_analysis")
            tools.append("remote_sensing")
        if signals["document"]:
            intents.append("document_understanding")
            tools.append("document")
        if signals["report"]:
            intents.append("report_generation")
            tools.append("report")
        if signals["email"]:
            intents.append("email_notification")
            tools.append("email")

        if has_confirmed_task and (signals["assessment"] or signals["disaster"]):
            primary_intent = "risk_assessment"
            intents.append(primary_intent)
            tools.append("risk_assessment")
            next_step = "run_risk_assessment"
        elif signals["disaster"]:
            primary_intent = "disaster_analysis"
            intents.append(primary_intent)
            if signals["knowledge"] or not any(
                tool in tools for tool in ("browser", "document", "remote_sensing")
            ):
                tools.insert(0, "graphrag")
            tools.append("task_draft")
            next_step = "confirm_task_draft"
            need_user_confirm = True
        elif signals["remote_sensing"]:
            primary_intent = "remote_sensing_analysis"
        elif signals["document"]:
            primary_intent = "document_understanding"
        elif signals["realtime"] or signals["screenshot"]:
            primary_intent = "realtime_search"
        elif signals["report"]:
            primary_intent = "report_generation"
        elif signals["email"]:
            primary_intent = "email_notification"
        else:
            primary_intent = "knowledge_or_general_qa"
            intents.append(primary_intent)
            tools.append("graphrag")

        tools = self._dedupe(tools)
        intents = self._dedupe(intents)
        confidence = self._estimate_confidence(primary_intent, signals, file_profile)

        return ToolResult(
            summary=self._build_summary(primary_intent, tools, next_step, need_user_confirm),
            confidence=confidence,
            need_user_confirm=need_user_confirm,
            data={
                "primary_intent": primary_intent,
                "intents": intents,
                "tools": tools,
                "next_step": next_step,
                "signals": signals,
            },
        )

    def _profile_files(self, files: list[dict[str, Any]]) -> dict[str, bool]:
        has_image = False
        has_document = False

        for file_info in files:
            file_name = str(file_info.get("name") or file_info.get("filename") or "")
            mime_type = str(file_info.get("type") or file_info.get("mime_type") or "").lower()
            extension = Path(file_name).suffix.lower()

            has_image = has_image or mime_type.startswith("image/") or extension in self.image_extensions
            has_document = (
                has_document
                or mime_type in {"application/pdf", "text/plain"}
                or "document" in mime_type
                or "spreadsheet" in mime_type
                or extension in self.document_extensions
            )

        return {"has_image": has_image, "has_document": has_document}

    def _has_confirmed_task(
        self,
        params: dict[str, Any],
        context: ToolContext | None,
        normalized_query: str,
    ) -> bool:
        if params.get("confirmed_task") or params.get("task_confirmed"):
            return True
        if context and context.metadata.get("confirmed_task"):
            return True
        return self._contains_any(normalized_query, self.confirmation_keywords)

    def _is_disaster_analysis_intent(self, normalized_query: str) -> bool:
        if self._contains_any(normalized_query, self.disaster_action_keywords):
            return True
        if "分析" in normalized_query and self._contains_any(normalized_query, self.hazard_keywords):
            return True
        return False

    def _estimate_confidence(
        self,
        primary_intent: str,
        signals: dict[str, bool],
        file_profile: dict[str, bool],
    ) -> float:
        if primary_intent == "knowledge_or_general_qa":
            return 0.68
        if file_profile["has_image"] or file_profile["has_document"]:
            return 0.86
        matched_signals = sum(1 for matched in signals.values() if matched)
        return min(0.92, 0.70 + matched_signals * 0.04)

    def _build_summary(
        self,
        primary_intent: str,
        tools: list[str],
        next_step: str,
        need_user_confirm: bool,
    ) -> str:
        summary = f"识别主意图：{primary_intent}；建议工具：{', '.join(tools)}；下一步：{next_step}"
        if need_user_confirm:
            summary += "。检测到灾害分析意图，将先生成临时任务草稿，等待用户确认后再进入正式分析"
        return summary

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)

    def _dedupe(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
