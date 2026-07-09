"""用户意图识别与工具规划。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agent.llm import complete_llm_json, is_llm_configured
from app.agent.tools.base_tool import BaseTool, ToolContext, ToolInput, ToolResult


ALLOWED_TOOLS = {
    "graphrag",
    "browser",
    "document",
    "remote_sensing",
    "task_draft",
    "risk_assessment",
    "report",
    "email",
}

ALLOWED_NEXT_STEPS = {
    "answer",
    "confirm_task_draft",
    "run_risk_assessment",
    "generate_report",
    "send_email",
}


class IntentRouterTool(BaseTool):
    name = "intent_router"
    description = "识别用户意图，并给出本轮对话建议调用的工具列表。"

    image_extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
    document_extensions = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".md"}

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
    realtime_keywords = ("最新", "实时", "今天", "现在", "新闻", "搜索", "预警", "公告", "网页", "浏览器", "网上")
    screenshot_keywords = ("截图", "截屏", "页面图", "网页图")
    remote_sensing_keywords = ("遥感", "卫星", "影像", "淹没", "水体", "ndvi", "ndwi", "sar", "tif", "tiff")
    document_keywords = ("文档", "资料", "pdf", "word", "docx", "excel", "表格", "上传", "文件", "报告内容")
    report_keywords = ("报告", "生成文档", "导出", "pdf", "word")
    email_keywords = ("邮件", "通知", "发送", "抄送")
    knowledge_keywords = ("为什么", "原因", "机制", "措施", "怎么", "如何", "解释")
    assessment_keywords = ("开始评估", "风险评估", "进行评估", "开始分析", "正式分析")
    confirmation_keywords = ("已确认", "确认", "保留这些", "就这些", "可以开始")

    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        query = tool_input.query.strip()
        params = tool_input.params or {}
        forced_tool = str(params.get("forced_tool") or "")

        forced_plan = self._forced_tool_plan(forced_tool, tool_input, query.lower())
        if forced_plan:
            return self._to_result(
                {
                    **forced_plan,
                    "primary_intent": f"manual_{forced_tool}",
                    "intents": [f"manual_{forced_tool}"],
                    "confidence": 0.99,
                    "reason": f"用户手动选择工作模式：{forced_tool}",
                    "signals": {"manual_tool_selected": True},
                    "router_source": "manual",
                }
            )

        quick_plan = self._route_with_rules(tool_input, context)
        if (
            quick_plan.get("primary_intent") in {"small_talk", "general_qa"}
            and not quick_plan.get("tools")
        ):
            quick_plan["router_source"] = "rules_fast"
            quick_plan["reason"] = "普通对话直接快速路由，不等待非流式意图识别。"
            return self._to_result(quick_plan)

        if self.use_llm and not params.get("disable_llm_router") and is_llm_configured():
            try:
                llm_plan = self._route_with_llm(tool_input, context)
                return self._to_result(llm_plan)
            except Exception as error:
                fallback = self._route_with_rules(tool_input, context)
                fallback["router_source"] = "rules_fallback"
                fallback["router_error"] = str(error)
                fallback["reason"] = f"LLM 意图识别失败，已启用规则兜底：{error}"
                return self._to_result(fallback)

        plan = self._route_with_rules(tool_input, context)
        plan["router_source"] = "rules"
        return self._to_result(plan)

    def _route_with_llm(self, tool_input: ToolInput, context: ToolContext | None) -> dict[str, Any]:
        file_profile = self._profile_files(tool_input.files)
        metadata = context.metadata if context else {}
        payload = {
            "query": tool_input.query,
            "files": tool_input.files,
            "file_profile": file_profile,
            "has_confirmed_task": self._has_confirmed_task(tool_input.params or {}, context, tool_input.query.lower()),
            "session_memory_keys": list(metadata.keys()),
            "available_tools": sorted(ALLOWED_TOOLS),
            "tool_policy": {
                "plain_qa": "普通问答可不调用工具，tools 为空，由 LLM 直接回答。",
                "deep_research": "深度研究使用 graphrag；如果有上传文档，可同时使用 document。",
                "document_qa": "针对上传 PDF/DOCX/TXT/MD 等文档，使用 document；必要时再 graphrag。",
                "browser": "需要最新、实时、网页、公告、预警、浏览器搜索或截图时使用 browser。",
                "remote_sensing": "图像识别、遥感、卫星影像、水体/淹没区域识别使用 remote_sensing。",
                "disaster_analysis": "识别出用户要进入灾害分析时，先生成 task_draft，need_user_confirm=true；确认前不要调用 risk_assessment。",
                "risk_assessment": "只有用户已确认任务信息或上下文 confirmed_task=true 后才调用 risk_assessment。",
                "report": "生成 Word/PDF 报告时调用 report；若缺少风险评估可先调用 risk_assessment。",
                "email": "发送邮件或通知调用 email。",
            },
        }
        plan = complete_llm_json(
            _router_system_prompt(),
            json.dumps(payload, ensure_ascii=False, default=str),
            temperature=0.0,
            timeout=45,
        )
        return self._normalize_plan(plan, router_source="llm")

    def _route_with_rules(self, tool_input: ToolInput, context: ToolContext | None) -> dict[str, Any]:
        query = tool_input.query.strip()
        normalized_query = query.lower()
        params = tool_input.params or {}

        if self._is_small_talk(normalized_query):
            return {
                "primary_intent": "small_talk",
                "intents": ["small_talk"],
                "tools": [],
                "next_step": "answer",
                "need_user_confirm": False,
                "confidence": 0.88,
                "reason": "识别为寒暄或普通短问答，不调用外部工具。",
                "signals": {"small_talk": True},
            }

        file_profile = self._profile_files(tool_input.files)
        has_confirmed_task = self._has_confirmed_task(params, context, normalized_query)
        signals = {
            "hazard_topic": self._contains_any(normalized_query, self.hazard_keywords),
            "disaster": self._contains_any(normalized_query, self.disaster_action_keywords)
            or ("分析" in normalized_query and self._contains_any(normalized_query, self.hazard_keywords)),
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

        tools: list[str] = []
        intents: list[str] = []
        next_step = "answer"
        need_user_confirm = False

        if signals["realtime"] or signals["screenshot"]:
            intents.append("realtime_search")
            tools.append("browser")
        if signals["remote_sensing"]:
            intents.append("remote_sensing_analysis")
            tools.append("remote_sensing")
        if signals["document"]:
            intents.append("document_understanding")
            tools.append("document")

        if has_confirmed_task and (signals["assessment"] or signals["disaster"]):
            primary_intent = "risk_assessment"
            intents.append(primary_intent)
            tools.append("risk_assessment")
            next_step = "run_risk_assessment"
        elif signals["disaster"]:
            primary_intent = "disaster_analysis"
            intents.append(primary_intent)
            if not any(tool in tools for tool in ("browser", "document", "remote_sensing")):
                tools.insert(0, "graphrag")
            tools.append("task_draft")
            next_step = "confirm_task_draft"
            need_user_confirm = True
        elif signals["report"]:
            primary_intent = "report_generation"
            intents.append(primary_intent)
            tools.extend(["risk_assessment", "report"])
            next_step = "generate_report"
        elif signals["email"]:
            primary_intent = "email_notification"
            intents.append(primary_intent)
            tools.append("email")
            next_step = "send_email"
        elif signals["remote_sensing"]:
            primary_intent = "remote_sensing_analysis"
        elif signals["document"]:
            primary_intent = "document_understanding"
        elif signals["realtime"] or signals["screenshot"]:
            primary_intent = "realtime_search"
        elif signals["hazard_topic"] or signals["knowledge"]:
            primary_intent = "knowledge_or_general_qa"
            intents.append(primary_intent)
            tools.append("graphrag")
        else:
            primary_intent = "general_qa"
            intents.append(primary_intent)
            tools = []

        return {
            "primary_intent": primary_intent,
            "intents": self._dedupe(intents),
            "tools": self._dedupe(tools),
            "next_step": next_step,
            "need_user_confirm": need_user_confirm,
            "confidence": self._estimate_confidence(primary_intent, signals, file_profile),
            "reason": "规则兜底完成意图识别。",
            "signals": signals,
        }

    def _normalize_plan(self, plan: dict[str, Any], *, router_source: str) -> dict[str, Any]:
        tools = [str(tool) for tool in plan.get("tools", []) if str(tool) in ALLOWED_TOOLS]
        primary_intent = str(plan.get("primary_intent") or "general_qa")
        intents = [str(intent) for intent in plan.get("intents", [])] or [primary_intent]
        next_step = str(plan.get("next_step") or "answer")
        if next_step not in ALLOWED_NEXT_STEPS:
            next_step = self._infer_next_step(primary_intent, tools, bool(plan.get("need_user_confirm", False)))
        confidence = float(plan.get("confidence") or 0.75)
        confidence = max(0.0, min(confidence, 1.0))
        need_user_confirm = bool(plan.get("need_user_confirm", False))

        if "risk_assessment" in tools and need_user_confirm:
            tools = [tool for tool in tools if tool != "risk_assessment"]
        if primary_intent == "disaster_analysis":
            tools = self._disaster_report_tools(tools)
            need_user_confirm = False
            next_step = "generate_report"

        return {
            "primary_intent": primary_intent,
            "intents": self._dedupe(intents),
            "tools": self._dedupe(tools),
            "next_step": next_step,
            "need_user_confirm": need_user_confirm,
            "confidence": confidence,
            "reason": str(plan.get("reason") or "LLM 完成意图识别。"),
            "signals": plan.get("signals") if isinstance(plan.get("signals"), dict) else {},
            "router_source": router_source,
        }

    def _infer_next_step(self, primary_intent: str, tools: list[str], need_user_confirm: bool) -> str:
        if need_user_confirm or primary_intent == "disaster_analysis":
            return "confirm_task_draft"
        if "email" in tools:
            return "send_email"
        if "report" in tools:
            return "generate_report"
        if "risk_assessment" in tools:
            return "run_risk_assessment"
        return "answer"

    def _disaster_report_tools(self, tools: list[str]) -> list[str]:
        ordered = ["browser", "graphrag"]
        ordered.extend(tool for tool in tools if tool in {"document", "remote_sensing"})
        ordered.extend(["task_draft", "memory", "risk_assessment", "report"])
        return self._dedupe(ordered)

    def _to_result(self, plan: dict[str, Any]) -> ToolResult:
        tools = plan.get("tools", [])
        reason = plan.get("reason") or "完成意图识别。"
        source = plan.get("router_source", "unknown")
        summary = (
            f"意图识别来源：{source}；主意图：{plan.get('primary_intent')}；"
            f"工具链：{', '.join(tools) if tools else '无'}；下一步：{plan.get('next_step')}。{reason}"
        )
        return ToolResult(
            summary=summary,
            confidence=float(plan.get("confidence") or 0.75),
            need_user_confirm=bool(plan.get("need_user_confirm")),
            data=plan,
        )

    def _forced_tool_plan(
        self,
        forced_tool: str,
        tool_input: ToolInput,
        normalized_query: str,
    ) -> dict[str, Any] | None:
        file_profile = self._profile_files(tool_input.files)
        has_realtime_need = self._contains_any(normalized_query, self.realtime_keywords) or self._contains_any(
            normalized_query, self.screenshot_keywords
        )

        if forced_tool == "browser":
            return {"tools": ["browser"], "next_step": "answer", "need_user_confirm": False}
        if forced_tool in {"research", "graphrag", "document"}:
            tools = ["document", "graphrag"] if file_profile["has_document"] else ["graphrag"]
            return {"tools": tools, "next_step": "answer", "need_user_confirm": False}
        if forced_tool == "remote_sensing":
            return {"tools": ["remote_sensing"], "next_step": "answer", "need_user_confirm": False}
        if forced_tool in {"disaster_analysis", "task_draft"}:
            tools: list[str] = ["browser", "graphrag"]
            if file_profile["has_document"]:
                tools.append("document")
            if file_profile["has_image"]:
                tools.append("remote_sensing")
            tools.extend(["task_draft", "memory", "risk_assessment", "report"])
            return {"tools": self._dedupe(tools), "next_step": "generate_report", "need_user_confirm": False}
        if forced_tool == "report":
            return {"tools": ["risk_assessment", "report"], "next_step": "generate_report", "need_user_confirm": False}
        if forced_tool == "email":
            return {"tools": ["email"], "next_step": "send_email", "need_user_confirm": False}
        if forced_tool == "risk_assessment":
            return {"tools": ["risk_assessment"], "next_step": "run_risk_assessment", "need_user_confirm": False}
        return None

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

    def _estimate_confidence(
        self,
        primary_intent: str,
        signals: dict[str, bool],
        file_profile: dict[str, bool],
    ) -> float:
        if primary_intent in {"general_qa", "knowledge_or_general_qa"}:
            return 0.72
        if file_profile["has_image"] or file_profile["has_document"]:
            return 0.86
        matched_signals = sum(1 for matched in signals.values() if matched)
        return min(0.92, 0.70 + matched_signals * 0.04)

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)

    def _is_small_talk(self, text: str) -> bool:
        normalized = text.strip().lower()
        greetings = {"你好", "您好", "hi", "hello", "哈喽", "在吗", "嗨", "早上好", "晚上好"}
        return normalized in greetings or (len(normalized) <= 6 and any(word in normalized for word in greetings))

    def _dedupe(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


def _router_system_prompt() -> str:
    return (
        "你是 SkyGuard Agent 的意图路由器，只输出 JSON 对象，不要输出 Markdown。"
        "你需要判断用户本轮输入是否需要调用工具，以及工具调用顺序。"
        "必须遵守：灾害分析先 task_draft 并 need_user_confirm=true；用户确认前不能 risk_assessment。"
        "普通问答可以 tools=[]。工具只能从 available_tools 中选择。"
        "JSON 字段：primary_intent, intents, tools, next_step, need_user_confirm, confidence, reason, signals。"
    )
