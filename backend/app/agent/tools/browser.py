"""浏览器实时检索工具（占位实现）。"""
from app.agent.tools.base_tool import BaseTool


class BrowserTool(BaseTool):
    name = "browser"
    description = "实时检索互联网信息，获取最新灾害动态与气象预警。"

    def run(self, query: str) -> str:
        # TODO: 接入 SerpAPI / Playwright 爬虫
        return (
            "【网络检索结果（占位）】\n"
            "来源：中国气象局\n"
            "内容：未来 24 小时目标区域存在暴雨红色预警，预计降水量超 150mm\n"
            "可信度：0.95"
        )
