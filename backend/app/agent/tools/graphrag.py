"""GraphRAG 知识检索与图谱推理工具。"""
from __future__ import annotations

from typing import Any

from app.agent.tools.base_tool import BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult


class GraphRAGTool(BaseTool):
    name = "graphrag"
    description = "基于灾害知识图谱与 LangChain 检索器进行原因解释、知识问答和应对措施生成。"

    builtin_knowledge = (
        {
            "keywords": ("暴雨", "洪涝", "洪水", "内涝", "强降雨"),
            "source": "builtin_disaster_graph",
            "path": "暴雨/持续强降雨 → 地表径流增加 → 排水能力不足/河流水位上涨 → 洪涝或城市内涝",
            "explanation": "暴雨会在短时间内增加地表径流，若排水系统、河道行洪或低洼区承载能力不足，就容易形成洪涝和城市内涝。",
            "suggestions": ("关注官方预警", "核查低洼区和积水点", "提前转移高风险区域人员"),
        },
        {
            "keywords": ("台风", "风暴潮", "强风"),
            "source": "builtin_disaster_graph",
            "path": "台风登陆 → 强风/风暴潮/强降雨 → 沿海淹没与城市内涝",
            "explanation": "台风会同时带来强风、风暴潮和强降雨，沿海低洼区、临时构筑物和城市排水系统风险会升高。",
            "suggestions": ("加固临时设施", "关注风暴潮预警", "排查沿海和低洼区域"),
        },
        {
            "keywords": ("地震", "震中", "余震"),
            "source": "builtin_disaster_graph",
            "path": "地壳能量释放 → 地表震动 → 建筑受损/滑坡/道路阻断",
            "explanation": "地震风险不仅来自建筑受损，也来自滑坡、道路阻断、堰塞湖等次生灾害。",
            "suggestions": ("核查震中周边建筑", "排查次生灾害", "保障救援通道"),
        },
    )

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        params = tool_input.params or {}
        query = tool_input.query.strip()

        retriever = params.get("retriever")
        if retriever:
            documents = self._retrieve_with_langchain(retriever, query)
            if documents:
                return self._build_document_result(query, documents, "langchain_retriever")

        graph_paths = params.get("graph_paths") or []
        if graph_paths:
            return self._build_graph_path_result(query, graph_paths)

        documents = params.get("documents") or params.get("knowledge_documents") or []
        if documents:
            return self._build_document_result(query, documents, "provided_documents")

        return self._build_builtin_result(query)

    def _retrieve_with_langchain(self, retriever: Any, query: str) -> list[Any]:
        if hasattr(retriever, "invoke"):
            return list(retriever.invoke(query) or [])
        if hasattr(retriever, "get_relevant_documents"):
            return list(retriever.get_relevant_documents(query) or [])
        if callable(retriever):
            return list(retriever(query) or [])
        return []

    def _build_document_result(
        self,
        query: str,
        documents: list[Any],
        retrieval_mode: str,
    ) -> ToolResult:
        normalized_documents = [self._normalize_document(document) for document in documents]
        evidence = [
            EvidenceItem(
                source=document["source"],
                type="retrieved_document",
                content=document["content"],
                confidence=document["confidence"],
                metadata=document["metadata"],
            )
            for document in normalized_documents
        ]
        answer = self._synthesize_from_documents(query, normalized_documents)

        return ToolResult(
            summary=answer,
            evidence=evidence,
            confidence=self._confidence_from_evidence(evidence, default=0.78),
            data={
                "retrieval_mode": retrieval_mode,
                "documents": normalized_documents,
                "reasoning_paths": [],
            },
        )

    def _build_graph_path_result(self, query: str, graph_paths: list[dict[str, Any]]) -> ToolResult:
        normalized_paths = [self._normalize_graph_path(path) for path in graph_paths]
        evidence = [
            EvidenceItem(
                source=path["source"],
                type="graph_path",
                content=path["path_text"],
                confidence=path["confidence"],
                metadata={"relation": path.get("relation")},
            )
            for path in normalized_paths
        ]
        path_text = "；".join(path["path_text"] for path in normalized_paths)

        return ToolResult(
            summary=f"围绕“{query}”检索到知识图谱推理路径：{path_text}。这些路径可作为灾害形成机制和应对建议的依据。",
            evidence=evidence,
            confidence=self._confidence_from_evidence(evidence, default=0.82),
            data={
                "retrieval_mode": "graph_paths",
                "documents": [],
                "reasoning_paths": normalized_paths,
            },
        )

    def _build_builtin_result(self, query: str) -> ToolResult:
        matched_items = [
            item
            for item in self.builtin_knowledge
            if any(keyword in query for keyword in item["keywords"])
        ]
        if not matched_items:
            matched_items = [self.builtin_knowledge[0]]

        evidence = [
            EvidenceItem(
                source=item["source"],
                type="graph_path",
                content=item["path"],
                confidence=0.68,
                metadata={"suggestions": item["suggestions"]},
            )
            for item in matched_items
        ]
        explanations = " ".join(item["explanation"] for item in matched_items)
        suggestions = self._dedupe(
            suggestion
            for item in matched_items
            for suggestion in item["suggestions"]
        )

        return ToolResult(
            summary=f"{explanations} 建议：{'、'.join(suggestions)}。",
            evidence=evidence,
            confidence=0.68,
            data={
                "retrieval_mode": "builtin_rules",
                "documents": [],
                "reasoning_paths": [item["path"] for item in matched_items],
            },
        )

    def _normalize_document(self, document: Any) -> dict[str, Any]:
        if isinstance(document, dict):
            content = str(document.get("page_content") or document.get("content") or "")
            metadata = dict(document.get("metadata") or {})
        else:
            content = str(getattr(document, "page_content", "") or getattr(document, "content", ""))
            metadata = dict(getattr(document, "metadata", {}) or {})

        return {
            "content": content,
            "metadata": metadata,
            "source": str(metadata.get("source") or metadata.get("url") or "langchain_retriever"),
            "confidence": float(metadata.get("confidence") or 0.78),
        }

    def _normalize_graph_path(self, path: dict[str, Any]) -> dict[str, Any]:
        nodes = path.get("nodes") or []
        path_text = path.get("path_text") or " → ".join(str(node) for node in nodes)
        return {
            "path_text": path_text,
            "relation": path.get("relation", "related_to"),
            "source": path.get("source", "knowledge_graph"),
            "confidence": float(path.get("confidence") or 0.8),
        }

    def _synthesize_from_documents(
        self,
        query: str,
        documents: list[dict[str, Any]],
    ) -> str:
        snippets = [document["content"] for document in documents if document["content"]]
        if not snippets:
            return f"围绕“{query}”完成检索，但未获得有效文本内容。"
        joined_snippets = "；".join(snippets[:3])
        return f"围绕“{query}”检索到相关知识：{joined_snippets}"

    def _confidence_from_evidence(self, evidence: list[EvidenceItem], default: float) -> float:
        confidences = [item.confidence for item in evidence if item.confidence is not None]
        if not confidences:
            return default
        return round(sum(confidences) / len(confidences), 2)

    def _dedupe(self, values: Any) -> list[str]:
        return list(dict.fromkeys(values))
