from __future__ import annotations

import json
from typing import Any

from app.agent.llm import complete_llm_json, is_llm_configured
from app.config import settings


KNOWN_LOCATIONS = (
    "北京", "上海", "广州", "深圳", "成都", "重庆", "武汉", "杭州", "南京", "郑州",
    "西安", "天津", "福州", "厦门", "长沙", "南昌", "哈尔滨", "长春", "沈阳", "石家庄",
    "昆明", "贵阳", "南宁", "海口", "兰州", "西宁", "银川", "乌鲁木齐", "拉萨", "青岛",
    "四川", "广东", "河南", "湖北", "浙江", "江苏", "福建", "云南", "贵州", "广西",
)

DISASTER_KEYWORDS = {
    "暴雨洪涝": ("暴雨", "洪涝", "洪水", "内涝", "强降雨", "积水"),
    "台风": ("台风", "强风", "风暴潮"),
    "地震": ("地震", "震中", "余震"),
    "滑坡泥石流": ("滑坡", "泥石流", "山体滑坡"),
    "火灾": ("火灾", "山火", "森林火灾"),
    "干旱": ("干旱", "缺水"),
}

RISK_KEYWORDS = ("低风险", "中风险", "高风险", "极高风险", "预警", "响应", "转移", "管制")
IMPACT_KEYWORDS = ("受灾", "影响", "淹没", "积水", "道路中断", "停电", "人员转移", "学校", "医院")
INFRASTRUCTURE_KEYWORDS = ("道路", "桥梁", "河道", "水库", "医院", "学校", "地铁", "机场", "排水", "电力")


def build_graph_payload(
    *,
    task_id: int | None,
    task_name: str | None,
    metadata: dict[str, Any],
    query: str = "",
) -> dict[str, Any]:
    source_payload = _source_payload(task_id=task_id, task_name=task_name, metadata=metadata, query=query)
    if is_llm_configured():
        try:
            return _normalize_payload(_extract_with_llm(source_payload), source_payload)
        except Exception:
            pass
    return _normalize_payload(_extract_with_rules(source_payload), source_payload)


def write_payload_to_neo4j(payload: dict[str, Any]) -> dict[str, Any]:
    if not (settings.NEO4J_URI and settings.NEO4J_USER and settings.NEO4J_PASSWORD):
        return {"enabled": False, "status": "skipped", "reason": "Neo4j 未配置"}

    try:
        from neo4j import GraphDatabase
    except ImportError as error:
        return {"enabled": False, "status": "failed", "reason": f"neo4j 依赖未安装：{error}"}

    driver = None
    try:
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        with driver.session() as session:
            for entity in payload["entities"]:
                session.run(
                    """
                    MERGE (n:SkyGuardEntity {task_id: $task_id, name: $name, entity_type: $entity_type})
                    SET n.description = $description,
                        n.source_type = $source_type,
                        n.source_ref = $source_ref,
                        n.confidence = $confidence,
                        n.updated_at = datetime()
                    """,
                    task_id=payload["task_id"],
                    name=entity["name"],
                    entity_type=entity["entity_type"],
                    description=entity.get("description"),
                    source_type=entity.get("source_type", "agent"),
                    source_ref=entity.get("source_ref"),
                    confidence=entity.get("confidence", 0.7),
                )
            for relation in payload["relations"]:
                session.run(
                    """
                    MERGE (s:SkyGuardEntity {task_id: $task_id, name: $source_name, entity_type: $source_type})
                    MERGE (t:SkyGuardEntity {task_id: $task_id, name: $target_name, entity_type: $target_type})
                    MERGE (s)-[r:RELATED_TO {relation_type: $relation_type, task_id: $task_id}]->(t)
                    SET r.evidence = $evidence,
                        r.source_ref = $source_ref,
                        r.confidence = $confidence,
                        r.updated_at = datetime()
                    """,
                    task_id=payload["task_id"],
                    source_name=relation["source_name"],
                    source_type=relation["source_type"],
                    target_name=relation["target_name"],
                    target_type=relation["target_type"],
                    relation_type=relation["relation_type"],
                    evidence=relation.get("evidence"),
                    source_ref=relation.get("source_ref"),
                    confidence=relation.get("confidence", 0.7),
                )
        return {
            "enabled": True,
            "status": "completed",
            "entity_count": len(payload["entities"]),
            "relation_count": len(payload["relations"]),
        }
    except Exception as error:
        return {"enabled": True, "status": "failed", "reason": str(error)}
    finally:
        if driver:
            driver.close()


def _source_payload(
    *,
    task_id: int | None,
    task_name: str | None,
    metadata: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    documents = _as_list(metadata.get("documents"))[:16]
    conversation_record = str(metadata.get("conversation_record") or "")

    text_blocks = [task_name or "", conversation_record]
    text_blocks.extend(str(item.get("content") or "") for item in documents if isinstance(item, dict))

    return {
        "task_id": task_id,
        "task_name": task_name,
        "query": "",
        "formal_memory": {},
        "risk_assessment": {},
        "documents": documents,
        "evidence": [],
        "artifacts": [],
        "conversation_record": conversation_record,
        "text": "\n".join(block for block in text_blocks if block)[:30000],
    }


def _extract_with_llm(source_payload: dict[str, Any]) -> dict[str, Any]:
    return complete_llm_json(
        _ingest_system_prompt(),
        json.dumps(source_payload, ensure_ascii=False, default=str)[:26000],
        temperature=0.0,
        timeout=60,
    )


def _ingest_system_prompt() -> str:
    return (
        "你是 SkyGuard GraphRAG 知识图谱抽取器，只输出 JSON。"
        "请只从用户已保存的对话记录和上传文档中抽取灾害知识图谱。"
        "JSON 字段必须包含 entities 和 relations。"
        "entities 每项字段：name, entity_type, description, source_type, source_ref, confidence。"
        "relations 每项字段：source_name, source_type, target_name, target_type, relation_type, evidence, source_ref, confidence。"
        "实体类型优先使用：灾害事件、灾害类型、地区、时间、风险等级、风险因素、影响对象、基础设施、证据、文档、报告、处置建议。"
        "关系类型优先使用：发生于、类型、时间、评估为、导致、影响、涉及、依据、来源于、建议、生成。"
        "不要使用临时执行轨迹、普通聊天历史、网页搜索中间结果或输入中没有依据的事实；如果证据不足，少抽取。"
    )


def _extract_with_rules(source_payload: dict[str, Any]) -> dict[str, Any]:
    text = source_payload["text"]
    task_name = source_payload.get("task_name") or "未命名灾害事件"
    formal_memory = _as_dict(source_payload.get("formal_memory"))
    risk_assessment = _as_dict(source_payload.get("risk_assessment"))

    event_name = formal_memory.get("title") or task_name
    disaster_type = formal_memory.get("disaster_type") or _match_disaster_type(text)
    locations = formal_memory.get("locations") or _match_locations(text)
    risk_level = risk_assessment.get("risk_level") or _match_risk_level(text)

    entities = [
        _entity(event_name, "灾害事件", f"由任务/对话抽取的灾害事件：{event_name}", 0.82),
    ]
    relations = []

    if disaster_type and disaster_type != "未知":
        entities.append(_entity(disaster_type, "灾害类型", "灾害类型实体", 0.78))
        relations.append(_relation(event_name, "灾害事件", disaster_type, "灾害类型", "类型", text, 0.78))

    for location in locations:
        entities.append(_entity(location, "地区", "受影响或被提及地区", 0.76))
        relations.append(_relation(event_name, "灾害事件", location, "地区", "发生于", text, 0.76))

    if risk_level:
        entities.append(_entity(risk_level, "风险等级", "风险评估结论", 0.76))
        relations.append(_relation(event_name, "灾害事件", risk_level, "风险等级", "评估为", text, 0.76))

    for factor in _extract_keyword_entities(text, RISK_KEYWORDS, "风险因素"):
        entities.append(factor)
        relations.append(_relation(event_name, "灾害事件", factor["name"], "风险因素", "涉及", text, 0.66))

    for target in _extract_keyword_entities(text, IMPACT_KEYWORDS, "影响对象"):
        entities.append(target)
        relations.append(_relation(event_name, "灾害事件", target["name"], "影响", "影响", text, 0.64))

    for infra in _extract_keyword_entities(text, INFRASTRUCTURE_KEYWORDS, "基础设施"):
        entities.append(infra)
        relations.append(_relation(event_name, "灾害事件", infra["name"], "基础设施", "影响", text, 0.62))

    for document in _as_list(source_payload.get("documents"))[:8]:
        source = str(document.get("source") or (document.get("metadata") or {}).get("source") or "上传文档")
        entities.append(_entity(source, "文档", "用户上传或解析得到的文档片段", 0.82, source_type="document", source_ref=source))
        relations.append(_relation(event_name, "灾害事件", source, "文档", "来源于", str(document.get("content") or ""), 0.82, source_ref=source))

    for item in _as_list(source_payload.get("evidence"))[:10]:
        source = str(item.get("source") or "证据")
        content = str(item.get("content") or "")
        evidence_name = source[:80]
        entities.append(_entity(evidence_name, "证据", content[:180], float(item.get("confidence") or 0.7), source_type=str(item.get("type") or "evidence")))
        relations.append(_relation(event_name, "灾害事件", evidence_name, "证据", "依据", content, float(item.get("confidence") or 0.7)))

    if source_payload.get("artifacts"):
        entities.append(_entity("分析产物", "报告", "截图、报告等工具产物集合", 0.74))
        relations.append(_relation(event_name, "灾害事件", "分析产物", "报告", "生成", text, 0.74))

    return {"entities": entities, "relations": relations}


def _normalize_payload(payload: dict[str, Any], source_payload: dict[str, Any]) -> dict[str, Any]:
    entities = [_normalize_entity(item) for item in _as_list(payload.get("entities"))]
    relations = [_normalize_relation(item) for item in _as_list(payload.get("relations"))]

    entity_keys = {(item["name"], item["entity_type"]) for item in entities}
    for relation in relations:
        for name_key, type_key in (
            (relation["source_name"], relation["source_type"]),
            (relation["target_name"], relation["target_type"]),
        ):
            if (name_key, type_key) not in entity_keys:
                entities.append(_entity(name_key, type_key, "", relation.get("confidence", 0.7)))
                entity_keys.add((name_key, type_key))

    entities = _dedupe_dicts(entities, ("name", "entity_type"))
    relations = _dedupe_dicts(relations, ("source_name", "target_name", "relation_type"))
    return {
        "task_id": source_payload.get("task_id"),
        "entities": entities[:80],
        "relations": relations[:120],
    }


def _normalize_entity(item: Any) -> dict[str, Any]:
    item = _as_dict(item)
    name = str(item.get("name") or "").strip()
    entity_type = str(item.get("entity_type") or item.get("type") or "概念").strip()
    return _entity(
        name=name[:255] or "未命名实体",
        entity_type=entity_type[:50] or "概念",
        description=str(item.get("description") or "")[:1000],
        confidence=_safe_float(item.get("confidence"), 0.7),
        source_type=str(item.get("source_type") or "agent")[:50],
        source_ref=str(item.get("source_ref") or "")[:500] or None,
    )


def _normalize_relation(item: Any) -> dict[str, Any]:
    item = _as_dict(item)
    return _relation(
        source_name=str(item.get("source_name") or item.get("source") or "未命名源")[:255],
        source_type=str(item.get("source_type") or "概念")[:50],
        target_name=str(item.get("target_name") or item.get("target") or "未命名目标")[:255],
        target_type=str(item.get("target_type") or "概念")[:50],
        relation_type=str(item.get("relation_type") or item.get("relation") or "相关")[:80],
        evidence=str(item.get("evidence") or "")[:2000],
        confidence=_safe_float(item.get("confidence"), 0.7),
        source_ref=str(item.get("source_ref") or "")[:500] or None,
    )


def _entity(
    name: str,
    entity_type: str,
    description: str,
    confidence: float,
    *,
    source_type: str = "agent",
    source_ref: str | None = None,
) -> dict[str, Any]:
    return {
        "name": str(name).strip()[:255],
        "entity_type": str(entity_type).strip()[:50],
        "description": str(description or "")[:1000],
        "source_type": source_type,
        "source_ref": source_ref,
        "confidence": round(float(confidence), 2),
    }


def _relation(
    source_name: str,
    source_type: str,
    target_name: str,
    target_type: str,
    relation_type: str,
    evidence: str,
    confidence: float,
    *,
    source_ref: str | None = None,
) -> dict[str, Any]:
    return {
        "source_name": str(source_name).strip()[:255],
        "source_type": str(source_type).strip()[:50],
        "target_name": str(target_name).strip()[:255],
        "target_type": str(target_type).strip()[:50],
        "relation_type": str(relation_type).strip()[:80],
        "evidence": _shorten(str(evidence or ""), 800),
        "source_ref": source_ref,
        "confidence": round(float(confidence), 2),
    }


def _match_disaster_type(text: str) -> str:
    for disaster_type, keywords in DISASTER_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return disaster_type
    return "未知"


def _match_locations(text: str) -> list[str]:
    return [location for location in KNOWN_LOCATIONS if location in text][:8]


def _match_risk_level(text: str) -> str | None:
    for level in ("极高风险", "高风险", "中风险", "低风险"):
        if level in text:
            return level
    return None


def _extract_keyword_entities(text: str, keywords: tuple[str, ...], entity_type: str) -> list[dict[str, Any]]:
    return [
        _entity(keyword, entity_type, f"文本中提及：{keyword}", 0.62)
        for keyword in keywords
        if keyword in text
    ][:10]


def _dedupe_dicts(items: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for item in items:
        key = tuple(item.get(part) for part in keys)
        if key in seen or not all(key):
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."
