"""文档解析工具（占位实现）。"""
from app.agent.tools.base_tool import BaseTool


class DocumentTool(BaseTool):
    name = "document"
    description = "解析用户上传的 PDF/Word/TXT 文档，提取关键信息写入任务记忆。"

    def run(self, query: str) -> str:
        # TODO: 接入 PyMuPDF + LangChain TextSplitter + Embedding
        return "【文档解析结果（占位）】已提取关键信息并写入任务记忆。"
