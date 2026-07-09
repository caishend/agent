from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.overview import (
    AdminPopulationStat,
    DisasterEvent,
    DisasterEvidence,
    KnowledgeGraphEntity,
    KnowledgeGraphRelation,
    PopulationDensity,
)
from app.models.task import Task
from app.services.graphrag_ingest import build_graph_payload, write_payload_to_neo4j
from app.services.local_geodata import (
    estimate_population_exposure,
    load_china_province_geojson,
    population_heatmap_points,
    population_dataset_status,
)
from app.services.population_cache import (
    admin_population_rows,
    estimate_population_exposure_from_db,
    heatmap_points_from_db,
    population_cache_status,
)
from app.utils import get_current_user_id

router = APIRouter()


CITY_PROFILE: dict[str, dict[str, Any]] = {
    "北京": {"province": "北京市", "city": "北京市", "lng": 116.4074, "lat": 39.9042, "density": 1334, "population": 21858000, "area": 16410},
    "上海": {"province": "上海市", "city": "上海市", "lng": 121.4737, "lat": 31.2304, "density": 3926, "population": 24870000, "area": 6340},
    "广州": {"province": "广东省", "city": "广州市", "lng": 113.2644, "lat": 23.1291, "density": 2598, "population": 18810000, "area": 7434},
    "深圳": {"province": "广东省", "city": "深圳市", "lng": 114.0579, "lat": 22.5431, "density": 8791, "population": 17790000, "area": 1997},
    "成都": {"province": "四川省", "city": "成都市", "lng": 104.0668, "lat": 30.5728, "density": 1460, "population": 21400000, "area": 14335},
    "重庆": {"province": "重庆市", "city": "重庆市", "lng": 106.5516, "lat": 29.5630, "density": 390, "population": 32130000, "area": 82402},
    "武汉": {"province": "湖北省", "city": "武汉市", "lng": 114.3054, "lat": 30.5931, "density": 1600, "population": 13740000, "area": 8569},
    "杭州": {"province": "浙江省", "city": "杭州市", "lng": 120.1551, "lat": 30.2741, "density": 731, "population": 12520000, "area": 16850},
    "南京": {"province": "江苏省", "city": "南京市", "lng": 118.7969, "lat": 32.0603, "density": 1435, "population": 9490000, "area": 6587},
    "郑州": {"province": "河南省", "city": "郑州市", "lng": 113.6254, "lat": 34.7466, "density": 1700, "population": 12830000, "area": 7567},
    "西安": {"province": "陕西省", "city": "西安市", "lng": 108.9398, "lat": 34.3416, "density": 1250, "population": 12990000, "area": 10108},
    "天津": {"province": "天津市", "city": "天津市", "lng": 117.2000, "lat": 39.0842, "density": 1150, "population": 13630000, "area": 11966},
    "福州": {"province": "福建省", "city": "福州市", "lng": 119.2965, "lat": 26.0745, "density": 700, "population": 8440000, "area": 11968},
    "厦门": {"province": "福建省", "city": "厦门市", "lng": 118.0894, "lat": 24.4798, "density": 3130, "population": 5300000, "area": 1701},
    "长沙": {"province": "湖南省", "city": "长沙市", "lng": 112.9388, "lat": 28.2282, "density": 870, "population": 10420000, "area": 11819},
    "南昌": {"province": "江西省", "city": "南昌市", "lng": 115.8582, "lat": 28.6829, "density": 860, "population": 6540000, "area": 7195},
    "哈尔滨": {"province": "黑龙江省", "city": "哈尔滨市", "lng": 126.5349, "lat": 45.8038, "density": 180, "population": 9880000, "area": 53100},
    "长春": {"province": "吉林省", "city": "长春市", "lng": 125.3235, "lat": 43.8171, "density": 390, "population": 9100000, "area": 24592},
    "沈阳": {"province": "辽宁省", "city": "沈阳市", "lng": 123.4315, "lat": 41.8057, "density": 750, "population": 9140000, "area": 12860},
    "昆明": {"province": "云南省", "city": "昆明市", "lng": 102.8332, "lat": 24.8801, "density": 415, "population": 8600000, "area": 21012},
    "贵阳": {"province": "贵州省", "city": "贵阳市", "lng": 106.6302, "lat": 26.6470, "density": 760, "population": 6400000, "area": 8034},
    "南宁": {"province": "广西壮族自治区", "city": "南宁市", "lng": 108.3669, "lat": 22.8170, "density": 410, "population": 8890000, "area": 22112},
    "海口": {"province": "海南省", "city": "海口市", "lng": 110.3312, "lat": 20.0311, "density": 990, "population": 2940000, "area": 2304},
    "兰州": {"province": "甘肃省", "city": "兰州市", "lng": 103.8343, "lat": 36.0611, "density": 360, "population": 4380000, "area": 13086},
    "银川": {"province": "宁夏回族自治区", "city": "银川市", "lng": 106.2309, "lat": 38.4872, "density": 410, "population": 2900000, "area": 9025},
    "乌鲁木齐": {"province": "新疆维吾尔自治区", "city": "乌鲁木齐市", "lng": 87.6168, "lat": 43.8256, "density": 160, "population": 4080000, "area": 14216},
    "拉萨": {"province": "西藏自治区", "city": "拉萨市", "lng": 91.1172, "lat": 29.6469, "density": 45, "population": 870000, "area": 29518},
    "青岛": {"province": "山东省", "city": "青岛市", "lng": 120.3826, "lat": 36.0671, "density": 920, "population": 10340000, "area": 11293},
    "石家庄": {"province": "河北省", "city": "石家庄市", "lng": 114.5149, "lat": 38.0428, "density": 730, "population": 11230000, "area": 14464},
    "太原": {"province": "山西省", "city": "太原市", "lng": 112.5489, "lat": 37.8706, "density": 820, "population": 5400000, "area": 6988},
    "呼和浩特": {"province": "内蒙古自治区", "city": "呼和浩特市", "lng": 111.7492, "lat": 40.8426, "density": 190, "population": 3550000, "area": 17224},
    "合肥": {"province": "安徽省", "city": "合肥市", "lng": 117.2272, "lat": 31.8206, "density": 850, "population": 9630000, "area": 11445},
}

DISASTER_KEYWORDS = {
    "暴雨洪涝": ("暴雨", "洪涝", "洪水", "内涝", "强降雨"),
    "台风": ("台风", "强风", "风暴潮"),
    "地震": ("地震", "震中", "余震"),
    "滑坡泥石流": ("滑坡", "泥石流", "山体滑坡"),
    "火灾": ("火灾", "山火", "森林火灾"),
    "干旱": ("干旱", "缺水"),
}

RISK_SCORE = {"低风险": 0.25, "中风险": 0.55, "高风险": 0.78, "极高风险": 0.9, "待评估": 0.4}
RISK_WEIGHT = {"低风险": 0.06, "中风险": 0.16, "高风险": 0.34, "极高风险": 0.58, "待评估": 0.12}
RISK_RADIUS = {"低风险": 3, "中风险": 8, "高风险": 15, "极高风险": 25, "待评估": 5}


@router.get("/summary")
def overview_summary(
    graph_task_id: int | None = Query(default=None),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _ensure_events_from_tasks(db, user_id)
    _refresh_population_impact(db, user_id)

    events = _user_events(db, user_id)
    population_rows = admin_population_rows(db)
    if not population_rows:
        population_rows = [
            row
            for row in db.query(PopulationDensity).order_by(PopulationDensity.density_per_km2.desc()).all()
            if not _is_demo_population(row)
        ]
    high_risk = [event for event in events if event.risk_level in {"高风险", "极高风险"}]
    involved_provinces = {event.province for event in events if event.province}
    affected_population = sum(event.estimated_affected_population or 0 for event in events)

    return {
        "data_source": {
            "events": "mysql:disaster_event joined with task",
            "knowledge_graph": "mysql:knowledge_graph_entity / knowledge_graph_relation",
            "population": "local_geotiff:first, mysql:population_density:fallback",
            "geojson": "backend/data local China boundary GeoJSON",
        },
        "metrics": {
            "event_count": len(events),
            "high_risk_count": len(high_risk),
            "province_count": len(involved_provinces),
            "estimated_affected_population": affected_population,
        },
        "events": [_event_payload(event) for event in events],
        "population_density": [_population_payload(row) for row in population_rows],
        "population_dataset": population_dataset_status(),
        "population_cache": population_cache_status(db),
        "knowledge_graph": _build_knowledge_graph(db, events, user_id, graph_task_id),
        "graph_scope": {"task_id": graph_task_id, "mode": "task" if graph_task_id else "all"},
    }


@router.get("/disasters")
def list_disasters(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _ensure_events_from_tasks(db, user_id)
    _refresh_population_impact(db, user_id)
    return [_event_payload(event) for event in _user_events(db, user_id)]


@router.get("/population-density")
def list_population_density(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    admin_rows = admin_population_rows(db, limit=50)
    if admin_rows:
        return [_population_payload(row) for row in admin_rows]
    rows = db.query(PopulationDensity).order_by(PopulationDensity.province, PopulationDensity.city).all()
    return [_population_payload(row) for row in rows if not _is_demo_population(row)]


@router.get("/china-geojson")
def china_geojson(user_id: int = Depends(get_current_user_id)):
    return load_china_province_geojson()


@router.get("/population-heatmap")
def population_heatmap(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    cached_points = heatmap_points_from_db(db)
    if cached_points:
        return {
            "points": cached_points,
            "dataset": {**population_cache_status(db), "available": True},
        }
    return {"points": population_heatmap_points(), "dataset": population_dataset_status()}


def _ensure_population_seed(db: Session) -> None:
    if db.query(PopulationDensity).first():
        return
    for profile in CITY_PROFILE.values():
        db.add(
            PopulationDensity(
                province=profile["province"],
                city=profile["city"],
                area_km2=profile["area"],
                population=profile["population"],
                density_per_km2=profile["density"],
                longitude=profile["lng"],
                latitude=profile["lat"],
                year=2024,
                data_source="内置演示数据，可替换为统计年鉴/WorldPop/LandScan 数据",
            )
        )
    db.commit()


def _ensure_events_from_tasks(db: Session, user_id: int) -> None:
    tasks = db.query(Task).filter(Task.user_id == user_id).all()
    for task in tasks:
        exists = db.query(DisasterEvent).filter(DisasterEvent.task_id == task.task_id).first()
        if exists:
            continue
        location_text = task.location or task.task_name or ""
        location = _match_location(location_text)
        disaster_type = task.disaster_type or _infer_disaster_type(task.task_name)
        risk_level = _risk_from_status(task.status)
        db.add(
            DisasterEvent(
                task_id=task.task_id,
                event_name=task.task_name,
                disaster_type=disaster_type or "未知",
                province=location.get("province"),
                city=location.get("city"),
                location_name=task.location or location.get("city") or location.get("province") or "待定位区域",
                longitude=location.get("lng"),
                latitude=location.get("lat"),
                risk_level=risk_level,
                severity_score=RISK_SCORE.get(risk_level, 0.4),
                status=_event_status_from_task(task.status),
                event_time=task.create_time or datetime.utcnow(),
                summary=f"由任务《{task.task_name}》自动生成的灾害态势事件。",
                source_type="task",
                confidence=0.65 if location else 0.45,
            )
        )
    db.commit()


def _refresh_population_impact(db: Session, user_id: int) -> None:
    changed = False
    for event in _user_events(db, user_id):
        radius = event.impact_radius_km or RISK_RADIUS.get(event.risk_level or "待评估", 5)
        weight = RISK_WEIGHT.get(event.risk_level or "待评估", 0.12)
        raster_result = estimate_population_exposure_from_db(db, event.longitude, event.latitude, radius)
        if not raster_result.get("available"):
            raster_result = estimate_population_exposure(event.longitude, event.latitude, radius)
        if raster_result.get("available"):
            exposed_population = int(raster_result.get("estimated_population") or 0)
            affected_population = int(exposed_population * weight)
            event.population_density = raster_result.get("mean_density_per_km2")
            event.estimated_affected_population = max(0, affected_population)
            event.summary = _append_population_summary(event.summary, exposed_population, event.estimated_affected_population)
            event.confidence = max(float(event.confidence or 0.0), 0.78)
            event.impact_radius_km = radius
            changed = True
            continue

        population = _match_population(db, event)
        if not population:
            continue
        impact_area = math.pi * radius * radius
        estimate = int(impact_area * population.density_per_km2 * weight)
        event.population_density = population.density_per_km2
        event.impact_radius_km = radius
        event.estimated_affected_population = max(0, estimate)
        changed = True
    if changed:
        db.commit()


def _append_population_summary(summary: str | None, exposed_population: int, affected_population: int) -> str:
    base = summary or ""
    marker = "本地人口栅格估算"
    if marker in base:
        return base
    return (
        f"{base} "
        f"{marker}：影响范围内暴露人口约 {exposed_population:,} 人，"
        f"按风险等级折算潜在受影响人口约 {affected_population:,} 人。"
    ).strip()


def _user_events(db: Session, user_id: int) -> list[DisasterEvent]:
    rows = (
        db.query(DisasterEvent)
        .outerjoin(Task, DisasterEvent.task_id == Task.task_id)
        .filter((Task.user_id == user_id) | (DisasterEvent.task_id.is_(None)))
        .order_by(
            DisasterEvent.task_id.is_(None),
            DisasterEvent.updated_at.desc(),
            DisasterEvent.event_id.desc(),
        )
        .all()
    )
    deduped: list[DisasterEvent] = []
    seen_task_ids: set[int] = set()
    seen_event_keys: set[tuple[str, str, str]] = set()
    for row in rows:
        if row.task_id:
            if row.task_id in seen_task_ids:
                continue
            seen_task_ids.add(row.task_id)
        key = _event_dedupe_key(row)
        if key in seen_event_keys:
            continue
        seen_event_keys.add(key)
        deduped.append(row)
    return deduped


def _event_dedupe_key(event: DisasterEvent) -> tuple[str, str, str]:
    name = (event.event_name or "").strip()
    location = (event.city or event.province or event.location_name or "").strip()
    disaster_type = (event.disaster_type or "").strip()
    return (name, location, disaster_type)


def _match_population(db: Session, event: DisasterEvent) -> PopulationDensity | None:
    query = db.query(PopulationDensity)
    if event.city:
        row = query.filter(PopulationDensity.city == event.city).first()
        if row:
            return None if _is_demo_population(row) else row
    if event.province:
        rows = query.filter(PopulationDensity.province == event.province).order_by(PopulationDensity.density_per_km2.desc()).all()
        return next((row for row in rows if not _is_demo_population(row)), None)
    return None


def _match_location(text: str) -> dict[str, Any]:
    for city_name, profile in CITY_PROFILE.items():
        if city_name in text or profile["city"] in text or profile["province"] in text:
            return profile
    return {}


def _infer_disaster_type(text: str) -> str:
    for disaster_type, keywords in DISASTER_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return disaster_type
    return "未知"


def _risk_from_status(status: str | None) -> str:
    if status == "ERROR":
        return "高风险"
    if status == "RUNNING":
        return "中风险"
    if status == "DONE":
        return "中风险"
    return "待评估"


def _event_status_from_task(status: str | None) -> str:
    if status == "RUNNING":
        return "analyzing"
    if status == "DONE":
        return "reported"
    if status == "ERROR":
        return "needs_review"
    return "monitoring"


def _event_payload(event: DisasterEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "task_id": event.task_id,
        "event_name": event.event_name,
        "disaster_type": event.disaster_type,
        "province": event.province,
        "city": event.city,
        "district": event.district,
        "location_name": event.location_name,
        "longitude": event.longitude,
        "latitude": event.latitude,
        "risk_level": event.risk_level,
        "severity_score": event.severity_score,
        "status": event.status,
        "summary": event.summary,
        "confidence": event.confidence,
        "report_path": event.report_path,
        "population_density": event.population_density,
        "impact_radius_km": event.impact_radius_km,
        "estimated_affected_population": event.estimated_affected_population or 0,
        "event_time": event.event_time.isoformat() if event.event_time else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }


def _population_payload(row: PopulationDensity | AdminPopulationStat) -> dict[str, Any]:
    if isinstance(row, AdminPopulationStat):
        return {
            "population_id": row.stat_id,
            "province": row.admin_name,
            "city": None,
            "district": None,
            "area_km2": row.area_km2,
            "population": row.population,
            "density_per_km2": row.density_per_km2,
            "year": row.year,
            "data_source": row.data_source,
            "longitude": row.longitude,
            "latitude": row.latitude,
        }
    return {
        "population_id": row.population_id,
        "province": row.province,
        "city": row.city,
        "district": row.district,
        "area_km2": row.area_km2,
        "population": row.population,
        "density_per_km2": row.density_per_km2,
        "year": row.year,
        "data_source": row.data_source,
        "longitude": row.longitude,
        "latitude": row.latitude,
    }


def _is_demo_population(row: PopulationDensity) -> bool:
    data_source = (row.data_source or "").lower()
    return "demo" in data_source or "seed" in data_source or "演示" in data_source


def _build_knowledge_graph(
    db: Session,
    events: list[DisasterEvent],
    user_id: int,
    graph_task_id: int | None,
) -> dict[str, Any]:
    kg_graph = _build_persisted_knowledge_graph(db, user_id, graph_task_id)
    if kg_graph["nodes"] or kg_graph["links"]:
        return kg_graph
    return _build_event_fallback_graph(events if graph_task_id is None else [event for event in events if event.task_id == graph_task_id])


def _build_persisted_knowledge_graph(db: Session, user_id: int, graph_task_id: int | None) -> dict[str, Any]:
    allowed_task_ids = [task.task_id for task in db.query(Task).filter(Task.user_id == user_id).all()]
    if graph_task_id and graph_task_id not in allowed_task_ids:
        return {"categories": [], "nodes": [], "links": []}

    entity_query = db.query(KnowledgeGraphEntity)
    relation_query = db.query(KnowledgeGraphRelation)
    if graph_task_id:
        entity_query = entity_query.filter(KnowledgeGraphEntity.task_id == graph_task_id)
        relation_query = relation_query.filter(KnowledgeGraphRelation.task_id == graph_task_id)
    elif allowed_task_ids:
        entity_query = entity_query.filter(KnowledgeGraphEntity.task_id.in_(allowed_task_ids))
        relation_query = relation_query.filter(KnowledgeGraphRelation.task_id.in_(allowed_task_ids))
    else:
        return {"categories": [], "nodes": [], "links": []}

    nodes = {}
    categories = set()
    for entity in entity_query.order_by(KnowledgeGraphEntity.updated_at.desc()).limit(160).all():
        node_id = f"kg:{entity.task_id}:{entity.entity_type}:{entity.name}"
        categories.add(entity.entity_type)
        nodes[(entity.name, entity.entity_type)] = {
            "id": node_id,
            "name": entity.name,
            "category": entity.entity_type,
            "value": entity.confidence or 0.7,
            "description": entity.description,
            "task_id": entity.task_id,
        }

    links = []
    for relation in relation_query.order_by(KnowledgeGraphRelation.created_at.desc()).limit(240).all():
        source_key = (relation.source_name, relation.source_type)
        target_key = (relation.target_name, relation.target_type)
        if source_key not in nodes:
            nodes[source_key] = {
                "id": f"kg:{relation.task_id}:{relation.source_type}:{relation.source_name}",
                "name": relation.source_name,
                "category": relation.source_type,
                "value": relation.confidence or 0.7,
                "task_id": relation.task_id,
            }
        if target_key not in nodes:
            nodes[target_key] = {
                "id": f"kg:{relation.task_id}:{relation.target_type}:{relation.target_name}",
                "name": relation.target_name,
                "category": relation.target_type,
                "value": relation.confidence or 0.7,
                "task_id": relation.task_id,
            }
        categories.update([relation.source_type, relation.target_type])
        links.append(
            {
                "source": nodes[source_key]["id"],
                "target": nodes[target_key]["id"],
                "label": relation.relation_type,
                "value": relation.relation_type,
                "evidence": relation.evidence,
                "task_id": relation.task_id,
            }
        )

    preferred = ["灾害事件", "灾害类型", "地区", "时间", "风险等级", "风险因素", "影响对象", "基础设施", "证据", "文档", "报告", "处置建议"]
    ordered_categories = [item for item in preferred if item in categories] + sorted(categories - set(preferred))
    return {"categories": ordered_categories, "nodes": list(nodes.values()), "links": links}


def _build_event_fallback_graph(events: list[DisasterEvent]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []

    def add_node(node_id: str, name: str, category: str, value: float | int = 1) -> None:
        nodes.setdefault(node_id, {"id": node_id, "name": name, "category": category, "value": value})

    for event in events:
        event_id = f"event:{event.event_id}"
        add_node(event_id, event.event_name, "灾害事件", event.severity_score or 0.4)

        if event.disaster_type:
            type_id = f"type:{event.disaster_type}"
            add_node(type_id, event.disaster_type, "灾害类型")
            links.append({"source": event_id, "target": type_id, "label": "类型"})

        location_name = event.city or event.province or event.location_name
        if location_name:
            location_id = f"location:{location_name}"
            add_node(location_id, location_name, "地区", event.population_density or 1)
            links.append({"source": event_id, "target": location_id, "label": "发生于"})

        risk_id = f"risk:{event.risk_level or '待评估'}"
        add_node(risk_id, event.risk_level or "待评估", "风险等级", event.severity_score or 0.4)
        links.append({"source": event_id, "target": risk_id, "label": "评估为"})

        if event.estimated_affected_population:
            pop_id = f"population:{event.event_id}"
            add_node(pop_id, f"影响约{event.estimated_affected_population:,}人", "人口影响", event.estimated_affected_population)
            links.append({"source": event_id, "target": pop_id, "label": "影响估算"})

        if event.report_path:
            report_id = f"report:{event.event_id}"
            add_node(report_id, "分析报告", "报告")
            links.append({"source": event_id, "target": report_id, "label": "生成"})

    return {
        "categories": ["灾害事件", "灾害类型", "地区", "风险等级", "人口影响", "报告"],
        "nodes": list(nodes.values()),
        "links": links,
    }


def sync_event_from_agent_session(db: Session, task_id: int, metadata: dict[str, Any]) -> None:
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        return

    formal_memory = metadata.get("formal_memory") or {}
    assessment = metadata.get("risk_assessment") or {}
    locations = formal_memory.get("locations") or []
    location_text = " ".join(str(item) for item in locations) or task.location or task.task_name
    location = _match_location(location_text)
    disaster_type = formal_memory.get("disaster_type") or task.disaster_type or _infer_disaster_type(task.task_name)
    risk_level = assessment.get("risk_level") or _risk_from_status(task.status)
    risk_score = assessment.get("risk_score") or RISK_SCORE.get(risk_level, 0.4)

    event = db.query(DisasterEvent).filter(DisasterEvent.task_id == task_id).first()
    if not event:
        event = DisasterEvent(task_id=task_id, event_name=task.task_name)
        db.add(event)

    event.event_name = formal_memory.get("title") or task.task_name
    event.disaster_type = disaster_type or "未知"
    event.province = location.get("province") or event.province
    event.city = location.get("city") or event.city
    event.location_name = location.get("city") or task.location or event.location_name
    event.longitude = location.get("lng") or event.longitude
    event.latitude = location.get("lat") or event.latitude
    event.risk_level = risk_level
    event.severity_score = float(risk_score or 0.4)
    event.status = "reported" if metadata.get("last_report_path") else "analyzing"
    event.event_time = task.create_time or event.event_time
    event.summary = _session_summary(task, formal_memory, assessment)
    event.source_type = "agent"
    event.confidence = 0.82 if assessment else 0.68
    event.report_path = metadata.get("last_report_path") or event.report_path
    db.commit()

    _sync_evidence_from_metadata(db, event, metadata)
    _sync_knowledge_graph_from_metadata(db, task, metadata)
    _refresh_population_impact(db, task.user_id)


def _session_summary(task: Task, formal_memory: dict[str, Any], assessment: dict[str, Any]) -> str:
    basis = assessment.get("basis") or []
    suggestions = assessment.get("suggestions") or []
    parts = [
        f"任务《{task.task_name}》已进入灾害态势库。",
        f"灾害类型：{formal_memory.get('disaster_type') or task.disaster_type or '未知'}。",
    ]
    if assessment.get("risk_level"):
        parts.append(f"风险等级：{assessment['risk_level']}，评分：{assessment.get('risk_score', '待评估')}。")
    if basis:
        parts.append(f"依据：{'；'.join(str(item) for item in basis[:3])}。")
    if suggestions:
        parts.append(f"建议：{'；'.join(str(item) for item in suggestions[:2])}。")
    return "".join(parts)


def _sync_evidence_from_metadata(db: Session, event: DisasterEvent, metadata: dict[str, Any]) -> None:
    if db.query(DisasterEvidence).filter(DisasterEvidence.event_id == event.event_id).first():
        return
    for item in (metadata.get("evidence") or [])[:12]:
        db.add(
            DisasterEvidence(
                event_id=event.event_id,
                source_type=str(item.get("type") or item.get("source") or "agent"),
                title=str(item.get("source") or "Agent evidence")[:255],
                url=(item.get("metadata") or {}).get("url") if isinstance(item.get("metadata"), dict) else None,
                content=str(item.get("content") or "")[:5000],
                confidence=float(item.get("confidence") or 0.7),
            )
        )
    db.commit()


def _sync_knowledge_graph_from_metadata(db: Session, task: Task, metadata: dict[str, Any]) -> None:
    payload = metadata.get("knowledge_graph")
    if not isinstance(payload, dict) or not payload.get("entities"):
        payload = build_graph_payload(
            task_id=task.task_id,
            task_name=task.task_name,
            metadata=metadata,
            query=task.task_name,
        )
        metadata["knowledge_graph"] = payload

    _upsert_knowledge_graph_payload(db, task.task_id, payload)
    neo4j_status = metadata.get("neo4j_ingest_status")
    if not neo4j_status:
        metadata["neo4j_ingest_status"] = write_payload_to_neo4j(payload)


def _upsert_knowledge_graph_payload(db: Session, task_id: int, payload: dict[str, Any]) -> None:
    for item in payload.get("entities", []):
        name = str(item.get("name") or "").strip()
        entity_type = str(item.get("entity_type") or "概念").strip()
        if not name:
            continue
        entity = (
            db.query(KnowledgeGraphEntity)
            .filter(
                KnowledgeGraphEntity.task_id == task_id,
                KnowledgeGraphEntity.name == name,
                KnowledgeGraphEntity.entity_type == entity_type,
            )
            .first()
        )
        if not entity:
            entity = KnowledgeGraphEntity(task_id=task_id, name=name, entity_type=entity_type)
            db.add(entity)
        entity.description = str(item.get("description") or "")[:1000]
        entity.source_type = str(item.get("source_type") or "agent")[:50]
        entity.source_ref = str(item.get("source_ref") or "")[:500] or None
        entity.confidence = float(item.get("confidence") or 0.7)

    for item in payload.get("relations", []):
        source_name = str(item.get("source_name") or "").strip()
        target_name = str(item.get("target_name") or "").strip()
        relation_type = str(item.get("relation_type") or "相关").strip()
        if not source_name or not target_name:
            continue
        relation = (
            db.query(KnowledgeGraphRelation)
            .filter(
                KnowledgeGraphRelation.task_id == task_id,
                KnowledgeGraphRelation.source_name == source_name,
                KnowledgeGraphRelation.target_name == target_name,
                KnowledgeGraphRelation.relation_type == relation_type,
            )
            .first()
        )
        if not relation:
            relation = KnowledgeGraphRelation(
                task_id=task_id,
                source_name=source_name,
                target_name=target_name,
                relation_type=relation_type,
            )
            db.add(relation)
        relation.source_type = str(item.get("source_type") or "概念")[:50]
        relation.target_type = str(item.get("target_type") or "概念")[:50]
        relation.evidence = str(item.get("evidence") or "")[:2000]
        relation.source_ref = str(item.get("source_ref") or "")[:500] or None
        relation.confidence = float(item.get("confidence") or 0.7)

    db.commit()
