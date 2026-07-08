"""
Agent 主入口：接收用户消息，规划任务，调用工具，流式返回结果。
"""
from typing import Generator
from sqlalchemy.orm import Session
from app.agent.memory import TaskMemory
from app.agent.tools.graphrag import GraphRAGTool
from app.agent.tools.browser import BrowserTool
from app.agent.tools.remote_sensing import RemoteSensingTool
from app.agent.tools.report import ReportTool


def run_agent(task_id: int, message: str, db: Session) -> Generator[dict, None, None]:
    """
    流式运行 Agent，每步产出一个事件 dict：
      {"type": "thinking" | "tool_call" | "tool_result" | "answer", "content": str, ...}
    """
    memory = TaskMemory(task_id=task_id, db=db)

    yield {"type": "thinking", "content": "正在分析任务..."}

    # 简单意图路由（后续可替换为 LLM 规划）
    tools_to_run = _plan(message)

    results = {}
    for tool_name in tools_to_run:
        yield {"type": "tool_call", "tool": tool_name, "content": f"调用工具：{tool_name}"}
        try:
            result = _call_tool(tool_name, task_id=task_id, message=message, memory=memory)
            results[tool_name] = result
            yield {"type": "tool_result", "tool": tool_name, "content": result}
            memory.update(tool_name, result)
        except Exception as e:
            yield {"type": "tool_result", "tool": tool_name, "content": f"工具调用失败：{e}"}

    # 生成最终回答
    answer = _synthesize(message, results, memory)
    yield {"type": "answer", "content": answer}


def _plan(message: str) -> list[str]:
    """根据消息内容决定调用哪些工具（占位实现，后续接 LLM 规划）。"""
    tools = ["graphrag"]
    if any(k in message for k in ["新闻", "最新", "实时", "预警"]):
        tools.append("browser")
    if any(k in message for k in ["影像", "遥感", "图片", "卫星"]):
        tools.append("remote_sensing")
    if any(k in message for k in ["报告", "生成", "输出"]):
        tools.append("report")
    return tools


def _call_tool(tool_name: str, **kwargs) -> str:
    tools = {
        "graphrag":       GraphRAGTool(),
        "browser":        BrowserTool(),
        "remote_sensing": RemoteSensingTool(),
        "report":         ReportTool(),
    }
    tool = tools.get(tool_name)
    if not tool:
        raise ValueError(f"未知工具：{tool_name}")
    return tool.run(kwargs["message"])


def _synthesize(message: str, results: dict, memory: TaskMemory) -> str:
    """占位：将各工具结果拼合为最终回答，后续替换为 LLM 总结。"""
    lines = [f"针对您的问题「{message}」，综合分析结果如下：\n"]
    for tool_name, result in results.items():
        lines.append(f"【{tool_name}】{result}\n")
    return "\n".join(lines)
