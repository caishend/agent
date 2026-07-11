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
    screenshot_keywords = ("截图", "截屏", "页面图", "网页图", "截一张")
    remote_sensing_keywords = ("遥感", "卫星", "影像", "淹没", "水体", "ndvi", "ndwi", "sar", "tif", "tiff", "识别图像")
    document_keywords = ("文档", "资料", "pdf", "word", "docx", "excel", "表格", "上传", "文件", "报告内容")
    report_keywords = ("报告", "生成文档", "导出", "pdf", "word")
    email_keywords = ("邮件", "通知", "发送", "抄送")
    knowledge_keywords = ("为什么", "原因", "机制", "措施", "怎么", "如何", "解释", "什么时候", "哪里", "影响")
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

        quick_plan = self._quick_browser_plan(query.lower(), tool_input)
        if quick_plan:
            return self._to_result(quick_plan)
        plain_plan = self._quick_plain_qa_plan(query.lower(), tool_input)
        if plain_plan:
            return self._to_result(plain_plan)

        if self.use_llm and not params.get("disable_llm_router") and is_llm_configured():
            try:
                return self._to_result(self._route_with_llm(tool_input, context))
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
                "plain_qa": "普通问答可不调工具，tools 为空，由 LLM 直接回答。",
                "deep_research": "深度研究使用 graphrag；如果有上传文档，可同时使用 document。",
                "document_qa": "针对上传 PDF/DOCX/TXT/MD 等文档，使用 document；必要时再 graphrag。",
                "browser": "需要最新、实时、网页、公告、预警、浏览器搜索或截图时使用 browser。",
                "remote_sensing": "图像识别、遥感、卫星影像、水体/淹没区域识别使用 remote_sensing。",
                "disaster_analysis": "灾害分析/灾害评估只允许调用 browser、graphrag、risk_assessment；不要生成报告。只有明确要求生成/导出报告时才调用 report。注意：解释灾害原因、为什么发生、形成机制属于知识问答/文档问答，不属于风险评估，不要调用 risk_assessment。",
                "graphrag": "GraphRAG 只检索当前任务上传的文档；知识图谱构建由上传/删除文档接口后台完成，不要在对话中构建图谱。",
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

        if signals["disaster"] and (signals["report"] or "报告" in normalized_query):
            primary_intent = "report_generation"
            intents.append(primary_intent)
            tools = ["report"]
            next_step = "generate_report"
        elif signals["disaster"]:
            primary_intent = "disaster_analysis"
            intents.append(primary_intent)
            tools = ["browser", "graphrag", "risk_assessment"]
            next_step = "run_risk_assessment"
        elif signals["report"]:
            primary_intent = "report_generation"
            intents.append(primary_intent)
            tools = ["report"]
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
        confidence = max(0.0, min(float(plan.get("confidence") or 0.75), 1.0))
        need_user_confirm = bool(plan.get("need_user_confirm", False))

        if "risk_assessment" in tools and need_user_confirm:
            tools = [tool for tool in tools if tool != "risk_assessment"]
        if self._is_browser_only_intent(primary_intent, intents, tools):
            tools = ["browser"]
            next_step = "answer"
            need_user_confirm = False
        if primary_intent == "disaster_analysis":
            tools = [tool for tool in tools if tool in {"browser", "graphrag", "risk_assessment"}]
            if "risk_assessment" not in tools:
                tools.append("risk_assessment")
            need_user_confirm = False
            next_step = "run_risk_assessment" if "risk_assessment" in tools else "answer"

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
        if need_user_confirm:
            return "answer"
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

        if forced_tool == "browser":
            return {"tools": ["browser"], "next_step": "answer", "need_user_confirm": False}
        if forced_tool in {"research", "graphrag", "document"}:
            tools = ["document", "graphrag"] if file_profile["has_document"] else ["graphrag"]
            return {"tools": tools, "next_step": "answer", "need_user_confirm": False}
        if forced_tool == "remote_sensing":
            return {"tools": ["remote_sensing"], "next_step": "answer", "need_user_confirm": False}
        if forced_tool == "disaster_analysis":
            return {
                "tools": ["browser", "graphrag", "risk_assessment"],
                "next_step": "run_risk_assessment",
                "need_user_confirm": False,
            }
        if forced_tool == "task_draft":
            return {"tools": ["task_draft", "memory"], "next_step": "answer", "need_user_confirm": False}
        if forced_tool == "report":
            return {"tools": ["report"], "next_step": "generate_report", "need_user_confirm": False}
        if forced_tool == "email":
            return {"tools": ["email"], "next_step": "send_email", "need_user_confirm": False}
        if forced_tool == "risk_assessment":
            return {"tools": ["risk_assessment"], "next_step": "run_risk_assessment", "need_user_confirm": False}
        return None

    def _quick_browser_plan(self, normalized_query: str, tool_input: ToolInput) -> dict[str, Any] | None:
        if tool_input.files:
            return None
        browser_signals = ("截图", "截屏", "截一张", "图片", "网页", "官网", "搜索", "最新", "介绍", "新闻", "预警")
        analysis_signals = ("灾害分析", "风险评估", "生成报告", "报告", "建档", "知识图谱", "构建图谱")
        if any(keyword in normalized_query for keyword in browser_signals) and not any(
            keyword in normalized_query for keyword in analysis_signals
        ):
            return {
                "primary_intent": "browser_search",
                "intents": ["browser_search"],
                "tools": ["browser"],
                "next_step": "answer",
                "need_user_confirm": False,
                "confidence": 0.9,
                "reason": "检测到明确的网页搜索/截图/图片请求，直接调用浏览器工具，跳过 LLM 意图识别。",
                "signals": {"browser_fast_path": True},
                "router_source": "rules_fast_path",
            }
        return None

    def _quick_plain_qa_plan(self, normalized_query: str, tool_input: ToolInput) -> dict[str, Any] | None:
        if tool_input.files or not normalized_query.strip():
            return None
        tool_signals = (
            "搜索",
            "最新",
            "网页",
            "截图",
            "报告",
            "邮件",
            "发送",
            "上传",
            "文件",
            "文档",
            "图片",
            "图像",
            "识别",
            "遥感",
            "灾害分析",
            "风险评估",
            "生成",
            "导出",
            "pdf",
            "word",
            "docx",
        )
        if any(keyword in normalized_query for keyword in tool_signals):
            return None
        return {
            "primary_intent": "general_qa",
            "intents": ["general_qa"],
            "tools": [],
            "next_step": "answer",
            "need_user_confirm": False,
            "confidence": 0.86,
            "reason": "普通对话快速路径：跳过意图识别 LLM，直接进入最终回答流。",
            "signals": {"plain_qa_fast_path": True},
            "router_source": "rules_fast_path",
        }

    def _profile_files(self, files: list[dict[str, Any]]) -> dict[str, bool]:
        has_image = False
        has_document = False
        for file_info in files:
            file_name = str(file_info.get("name") or file_info.get("filename") or file_info.get("path") or "")
            mime_type = str(file_info.get("type") or file_info.get("mime_type") or "").lower()
            extension = Path(file_name).suffix.lower()
            has_image = has_image or mime_type.startswith("image/") or extension in self.image_extensions
            has_document = (
                has_document
                or extension in self.document_extensions
                or any(token in mime_type for token in ("pdf", "word", "document", "text", "spreadsheet"))
            )
        return {"has_image": has_image, "has_document": has_document, "file_count": len(files)}

    def _has_confirmed_task(self, params: dict[str, Any], context: ToolContext | None, query: str) -> bool:
        metadata = context.metadata if context else {}
        return bool(
            params.get("confirmed_task")
            or metadata.get("confirmed_task")
            or metadata.get("formal_memory")
            or self._contains_any(query, self.confirmation_keywords)
        )

    def _estimate_confidence(self, primary_intent: str, signals: dict[str, bool], file_profile: dict[str, Any]) -> float:
        if primary_intent in {"small_talk", "realtime_search"}:
            return 0.88
        score = 0.62 + sum(0.06 for value in signals.values() if value)
        if file_profile.get("file_count"):
            score += 0.08
        return min(score, 0.94)

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword and keyword in text for keyword in keywords)

    def _is_small_talk(self, normalized: str) -> bool:
        greetings = {"你好", "您好", "hi", "hello", "哈喽", "在吗", "嗨", "早上好", "晚上好"}
        return normalized in greetings or (len(normalized) <= 6 and any(word in normalized for word in greetings))

    def _dedupe(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    def _is_browser_only_intent(self, primary_intent: str, intents: list[str], tools: list[str]) -> bool:
        normalized_intents = {item.lower() for item in intents}
        primary = primary_intent.lower()
        if "browser" not in tools:
            return False
        if any(tool in tools for tool in ("task_draft", "risk_assessment", "report", "document", "graphrag", "remote_sensing")):
            return False
        return any(
            keyword in primary or keyword in normalized_intents
            for keyword in ("screenshot", "get_screenshot", "realtime_search", "browser", "web_search")
        )


def _router_system_prompt() -> str:
    return (
        "你是 SkyGuard Agent 的意图路由器，只输出 JSON 对象，不要输出 Markdown。"
        "你需要判断用户本轮输入是否需要调用工具，以及工具调用顺序。"
        "普通问答可以 tools=[]。工具只能从 available_tools 中选择。"
        "如果用户只是要求网页搜索、最新信息或截图，tools 只能包含 browser。"
        "灾害分析/灾害评估不等于生成报告，只能使用 browser、graphrag、risk_assessment。"
        "如果用户只是询问灾害原因、为什么发生、形成机制、如何导致等解释型问题，应视为知识问答/文档问答，只使用 document/graphrag，不要调用 risk_assessment。"
        "只有用户明确要求风险评估、灾害评估、风险等级、影响人口、处置建议或正式分析时，才允许调用 risk_assessment。"
        "只有用户明确说生成报告、导出报告、Word、PDF 时，才允许 tools 包含 report。"
        "报告生成只负责整合已保存对话记录和当前任务相关文档，不要规划联网搜索或风险评估。"
        "GraphRAG 只用于检索当前任务上传的文档；不要规划知识图谱构建工具。"
        "JSON 字段：primary_intent, intents, tools, next_step, need_user_confirm, confidence, reason, signals。"
    )
