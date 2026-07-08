"""用户意图识别与工具规划工具。"""
from app.agent.tools.base_tool import BaseTool, ToolContext, ToolResult


class IntentRouterTool(BaseTool):
    name = "intent_router"
    description = "识别用户意图，并给出本轮对话建议调用的工具列表。"

    def run(self, query: str, context: ToolContext | None = None) -> ToolResult:
        intents: list[str] = []
        tools: list[str] = []

        if any(word in query for word in ["报告", "生成文档", "导出"]):
            intents.append("report_generation")
            tools.append("report")
        if any(word in query for word in ["邮件", "通知", "发送"]):
            intents.append("email_notification")
            tools.append("email")
        if any(word in query for word in ["风险", "评估", "分析灾害", "灾害分析", "应急方案"]):
            intents.append("disaster_analysis")
            tools.extend(["task_draft", "risk_assessment"])
        if any(word in query for word in ["新闻", "最新", "实时", "预警", "搜索", "公告", "截图", "网页"]):
            intents.append("realtime_search")
            tools.append("browser")
        if any(word in query for word in ["影像", "遥感", "卫星", "淹没", "水体", "图片"]):
            intents.append("remote_sensing_analysis")
            tools.append("remote_sensing")
        if any(word in query for word in ["文档", "PDF", "Word", "Excel", "上传资料"]):
            intents.append("document_understanding")
            tools.append("document")

        if not intents:
            intents.append("knowledge_or_general_qa")
            tools.append("graphrag")
        elif "graphrag" not in tools and any(word in query for word in ["为什么", "原因", "机制", "措施", "怎么办"]):
            tools.insert(0, "graphrag")

        deduped_tools = list(dict.fromkeys(tools))
        return ToolResult(
            summary=f"识别意图：{', '.join(intents)}；建议工具：{', '.join(deduped_tools)}",
            data={"intents": intents, "tools": deduped_tools},
            confidence=0.70,
        )
