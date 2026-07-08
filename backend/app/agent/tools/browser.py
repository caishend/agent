"""浏览器检索、网页截图与截图理解工具（占位实现）。"""
from app.agent.tools.base_tool import BaseTool, ToolContext, ToolResult


class BrowserTool(BaseTool):
    name = "browser"
    description = "实时检索互联网信息，打开网页，截取页面，并理解网页截图中的地图、图表和预警信息。"

    def run(self, query: str, context: ToolContext | None = None) -> ToolResult:
        # TODO: 接入 Search API + Playwright + VLM 截图理解
        return ToolResult(
            summary=(
                "【浏览器检索结果（占位）】\n"
                "来源：中国气象局\n"
                "内容：未来 24 小时目标区域存在暴雨红色预警，预计降水量超 150mm\n"
                "截图理解：如页面包含地图、雷达图或公告截图，Agent 将主动截图并提取视觉证据。"
            ),
            evidence=[
                {
                    "source": "中国气象局",
                    "type": "web",
                    "content": "未来 24 小时目标区域存在暴雨红色预警，预计降水量超 150mm",
                    "confidence": 0.95,
                }
            ],
            confidence=0.95,
        )
