from __future__ import annotations

from app.agent.tools.base_tool import BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult
from app.services.graphrag_ingest import build_graph_payload, write_payload_to_neo4j


class GraphRAGIngestTool(BaseTool):
    name = "graphrag_ingest"
    description = "只从用户保存的对话记录和上传文档中抽取实体关系，并写入 GraphRAG 知识图谱。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        metadata = context.metadata if context else {}
        task_id = context.task_id if context else None
        task_name = str(metadata.get("task_name") or metadata.get("conversation_record") or "")[:80] or None

        payload = build_graph_payload(
            task_id=task_id,
            task_name=task_name,
            metadata=metadata,
            query=tool_input.query,
        )
        neo4j_status = write_payload_to_neo4j(payload)

        if context:
            context.metadata["knowledge_graph"] = payload
            context.metadata["neo4j_ingest_status"] = neo4j_status

        entity_count = len(payload["entities"])
        relation_count = len(payload["relations"])
        status_text = neo4j_status.get("status", "skipped")

        return ToolResult(
            summary=f"GraphRAG 入库完成：抽取 {entity_count} 个实体、{relation_count} 条关系；Neo4j 状态：{status_text}。",
            evidence=[
                EvidenceItem(
                    source="graphrag_ingest",
                    type="knowledge_graph",
                    content=f"已构建任务级知识图谱，实体 {entity_count} 个，关系 {relation_count} 条。",
                    confidence=0.82 if relation_count else 0.55,
                    metadata={"neo4j_status": neo4j_status},
                )
            ],
            confidence=0.82 if relation_count else 0.55,
            data={
                "graph_status": "completed",
                "task_id": task_id,
                "entity_count": entity_count,
                "relation_count": relation_count,
                "entities": payload["entities"],
                "relations": payload["relations"],
                "neo4j": neo4j_status,
            },
        )
