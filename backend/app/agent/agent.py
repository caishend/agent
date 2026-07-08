"""
Agent 主入口：接收用户消息，规划任务，调用工具，流式返回结果。
"""
from typing import Generator
from sqlalchemy.orm import Session
from app.agent.memory import TaskMemory
from app.agent.tools.base_tool import BaseTool, ToolContext, ToolResult
from app.agent.tools.intent_router import IntentRouterTool
from app.agent.tools.graphrag import GraphRAGTool
from app.agent.tools.browser import BrowserTool
from app.agent.tools.document import DocumentTool
from app.agent.tools.remote_sensing import RemoteSensingTool
from app.agent.tools.task_draft import TaskDraftTool
from app.agent.tools.memory import MemoryTool
from app.agent.tools.risk_assessment import RiskAssessmentTool
from app.agent.tools.report import ReportTool
from app.agent.tools.email import EmailTool


def run_agent(task_id: int, message: str, db: Session) -> Generator[dict, None, None]:
    """
    流式运行 Agent，每步产出一个事件 dict：
      {"type": "thinking" | "tool_call" | "tool_result" | "answer", "content": str, ...}
    """
    memory = TaskMemory(task_id=task_id, db=db)

    yield {"type": "thinking", "content": "正在分析任务..."}

    context = ToolContext(task_id=task_id)
    router_result = IntentRouterTool().run(message, context)
    tools_to_run = router_result.data.get("tools", ["graphrag"])
    yield {"type": "intent", "content": router_result.to_text(), "data": router_result.data}

    results = {}
    for tool_name in tools_to_run:
        yield {"type": "tool_call", "tool": tool_name, "content": f"调用工具：{tool_name}"}
        try:
            result = _call_tool(tool_name, message=message, context=context)
            results[tool_name] = result
            yield {
                "type": "tool_result",
                "tool": tool_name,
                "content": result.to_text(),
                "data": result.data,
                "evidence": result.evidence,
                "artifacts": result.artifacts,
                "need_user_confirm": result.need_user_confirm,
            }
            memory.update(tool_name, result.to_text())
        except Exception as e:
            yield {"type": "tool_result", "tool": tool_name, "content": f"工具调用失败：{e}"}

    # 生成最终回答
    answer = _synthesize(message, results, memory)
    yield {"type": "answer", "content": answer}


def _tool_registry() -> dict[str, BaseTool]:
    return {
        "graphrag": GraphRAGTool(),
        "browser": BrowserTool(),
        "document": DocumentTool(),
        "remote_sensing": RemoteSensingTool(),
        "task_draft": TaskDraftTool(),
        "memory": MemoryTool(),
        "risk_assessment": RiskAssessmentTool(),
        "report": ReportTool(),
        "email": EmailTool(),
    }


def _call_tool(tool_name: str, message: str, context: ToolContext) -> ToolResult:
    tools = _tool_registry()
    tool = tools.get(tool_name)
    if not tool:
        raise ValueError(f"未知工具：{tool_name}")
    return tool.run(message, context)


def _synthesize(message: str, results: dict[str, ToolResult], memory: TaskMemory) -> str:
    """占位：将各工具结果拼合为最终回答，后续替换为 LLM 总结。"""
    lines = [f"针对您的问题「{message}」，综合分析结果如下：\n"]
    for tool_name, result in results.items():
        lines.append(f"【{tool_name}】{result.to_text()}\n")
    return "\n".join(lines)
