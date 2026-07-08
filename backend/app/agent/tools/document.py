"""文档解析工具。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.tools.base_tool import BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult


class DocumentTool(BaseTool):
    name = "document"
    description = "解析用户上传的 PDF/Word/TXT 文档，提取关键信息并形成可供 GraphRAG 使用的文档片段。"

    text_extensions = {".txt", ".md", ".csv", ".json"}
    supported_loader_extensions = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx"}

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        params = tool_input.params or {}

        loader = params.get("loader")
        if loader:
            raw_documents = self._load_with_langchain(loader)
            document_mode = "langchain_loader"
        elif params.get("documents") or params.get("texts"):
            raw_documents = params.get("documents") or params.get("texts")
            document_mode = "provided_documents"
        elif tool_input.files:
            raw_documents = self._load_files(tool_input.files)
            document_mode = "file_loader"
        else:
            return ToolResult(
                summary="未收到可解析文档。请上传文件，或传入 LangChain loader / documents。",
                need_user_confirm=True,
                confidence=0.3,
                data={"document_mode": "missing_document", "documents": [], "key_points": []},
            )

        documents = [self._normalize_document(document) for document in raw_documents]
        documents = [document for document in documents if document["content"]]
        key_points = self._extract_key_points(documents)
        evidence = self._build_evidence(documents)
        confidence = 0.82 if documents else 0.4

        return ToolResult(
            summary=self._build_summary(documents, key_points),
            evidence=evidence,
            confidence=confidence,
            need_user_confirm=True,
            data={
                "document_mode": document_mode,
                "documents": documents,
                "key_points": key_points,
                "graph_rag_ready": bool(documents),
            },
        )

    def _load_with_langchain(self, loader: Any) -> list[Any]:
        if hasattr(loader, "load"):
            return list(loader.load() or [])
        if hasattr(loader, "lazy_load"):
            return list(loader.lazy_load() or [])
        if callable(loader):
            return list(loader() or [])
        return []

    def _load_files(self, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        documents = []
        for file_info in files:
            file_path = Path(str(file_info.get("path") or ""))
            file_name = str(file_info.get("name") or file_path.name)
            extension = file_path.suffix.lower()

            if extension in self.text_extensions and file_path.exists():
                documents.append(
                    {
                        "content": file_path.read_text(encoding="utf-8"),
                        "metadata": {"source": file_name, "path": str(file_path)},
                    }
                )
            elif extension in self.supported_loader_extensions:
                documents.extend(self._load_file_with_langchain_loader(file_path, file_name))

        return documents

    def _load_file_with_langchain_loader(self, file_path: Path, file_name: str) -> list[dict[str, Any]]:
        if not file_path.exists():
            return []
        loader = self._create_langchain_loader(file_path)
        if not loader:
            return []
        raw_documents = self._load_with_langchain(loader)
        documents = []
        for document in raw_documents:
            normalized = self._normalize_document(document)
            normalized["source"] = normalized["source"] or file_name
            normalized["metadata"].setdefault("source", file_name)
            documents.append(normalized)
        return documents

    def _create_langchain_loader(self, file_path: Path) -> Any | None:
        extension = file_path.suffix.lower()
        try:
            if extension == ".pdf":
                from langchain_community.document_loaders import PyMuPDFLoader

                return PyMuPDFLoader(str(file_path))
            if extension == ".docx":
                from langchain_community.document_loaders import Docx2txtLoader

                return Docx2txtLoader(str(file_path))
        except ImportError:
            return None
        return None

    def _normalize_document(self, document: Any) -> dict[str, Any]:
        if isinstance(document, str):
            return {"content": document, "metadata": {}, "source": "inline_text"}

        if isinstance(document, dict):
            content = str(document.get("page_content") or document.get("content") or document.get("text") or "")
            metadata = dict(document.get("metadata") or {})
        else:
            content = str(getattr(document, "page_content", "") or getattr(document, "content", ""))
            metadata = dict(getattr(document, "metadata", {}) or {})

        source = str(metadata.get("source") or metadata.get("file_name") or metadata.get("path") or "uploaded_document")
        return {"content": content.strip(), "metadata": metadata, "source": source}

    def _extract_key_points(self, documents: list[dict[str, Any]]) -> list[str]:
        key_points = []
        for document in documents:
            for sentence in self._split_sentences(document["content"]):
                if self._is_key_sentence(sentence):
                    key_points.append(sentence)
                if len(key_points) >= 8:
                    return key_points

        if not key_points:
            key_points = [self._shorten(document["content"], 80) for document in documents[:3]]

        return key_points

    def _build_evidence(self, documents: list[dict[str, Any]]) -> list[EvidenceItem]:
        return [
            EvidenceItem(
                source=document["source"],
                type="document",
                content=self._shorten(document["content"], 240),
                confidence=0.82,
                metadata=document["metadata"],
            )
            for document in documents
        ]

    def _build_summary(self, documents: list[dict[str, Any]], key_points: list[str]) -> str:
        if not documents:
            return "文档解析完成，但未提取到有效文本。"
        key_point_text = "；".join(key_points[:4]) if key_points else "暂无明确关键句"
        return f"已解析 {len(documents)} 个文档片段，提取关键信息：{key_point_text}"

    def _split_sentences(self, text: str) -> list[str]:
        normalized = text.replace("\n", "。")
        for delimiter in ("；", ";", "！", "？", "!", "?"):
            normalized = normalized.replace(delimiter, "。")
        return [sentence.strip() for sentence in normalized.split("。") if sentence.strip()]

    def _is_key_sentence(self, sentence: str) -> bool:
        keywords = (
            "预警",
            "风险",
            "灾害",
            "洪涝",
            "暴雨",
            "台风",
            "地震",
            "滑坡",
            "泥石流",
            "应急",
            "转移",
            "管制",
            "低洼",
            "医院",
            "学校",
        )
        return any(keyword in sentence for keyword in keywords)

    def _shorten(self, content: str, limit: int) -> str:
        if len(content) <= limit:
            return content
        return content[:limit] + "..."
