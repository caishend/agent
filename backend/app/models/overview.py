from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db import Base


class DisasterEvent(Base):
    __tablename__ = "disaster_event"

    event_id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("task.task_id"), nullable=True, index=True)

    event_name = Column(String(255), nullable=False)
    disaster_type = Column(String(50), nullable=False, default="未知")

    province = Column(String(50), index=True)
    city = Column(String(50), index=True)
    district = Column(String(50))
    location_name = Column(String(255))

    longitude = Column(Float)
    latitude = Column(Float)

    risk_level = Column(String(20), default="待评估")
    severity_score = Column(Float, default=0.4)
    status = Column(String(30), default="monitoring")

    event_time = Column(DateTime)
    summary = Column(Text)
    source_type = Column(String(50), default="task")
    confidence = Column(Float, default=0.7)
    report_path = Column(String(500))

    estimated_affected_population = Column(Integer, default=0)
    population_density = Column(Float)
    impact_radius_km = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    evidences = relationship("DisasterEvidence", back_populates="event", cascade="all, delete-orphan")


class DisasterEvidence(Base):
    __tablename__ = "disaster_evidence"

    evidence_id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("disaster_event.event_id"), nullable=False, index=True)

    source_type = Column(String(50), default="unknown")
    title = Column(String(255))
    url = Column(String(500))
    content = Column(Text)
    artifact_path = Column(String(500))
    confidence = Column(Float, default=0.7)

    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("DisasterEvent", back_populates="evidences")


class PopulationDensity(Base):
    __tablename__ = "population_density"

    population_id = Column(Integer, primary_key=True, index=True)

    province = Column(String(50), nullable=False, index=True)
    city = Column(String(50), index=True)
    district = Column(String(50), index=True)

    area_km2 = Column(Float)
    population = Column(Integer)
    density_per_km2 = Column(Float, nullable=False)

    year = Column(Integer, default=2024)
    data_source = Column(String(255), default="demo_seed")

    longitude = Column(Float)
    latitude = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)


class AdminPopulationStat(Base):
    __tablename__ = "admin_population_stat"
    __table_args__ = (
        UniqueConstraint("admin_level", "admin_name", "year", name="uq_admin_population_level_name_year"),
    )

    stat_id = Column(Integer, primary_key=True, index=True)
    admin_level = Column(String(30), nullable=False, index=True)
    admin_name = Column(String(100), nullable=False, index=True)
    parent_name = Column(String(100), index=True)

    population = Column(Integer, default=0)
    area_km2 = Column(Float)
    density_per_km2 = Column(Float, default=0)
    longitude = Column(Float)
    latitude = Column(Float)

    year = Column(Integer, default=2025, index=True)
    data_source = Column(String(255), default="local_worldpop_geotiff_preprocessed")
    sample_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PopulationRasterSample(Base):
    __tablename__ = "population_raster_sample"
    __table_args__ = (
        UniqueConstraint("longitude", "latitude", "year", name="uq_population_sample_lng_lat_year"),
    )

    sample_id = Column(Integer, primary_key=True, index=True)
    longitude = Column(Float, nullable=False, index=True)
    latitude = Column(Float, nullable=False, index=True)

    population_value = Column(Float, nullable=False)
    density_per_km2 = Column(Float, default=0)
    province = Column(String(100), index=True)

    year = Column(Integer, default=2025, index=True)
    data_source = Column(String(255), default="local_worldpop_geotiff_preprocessed")

    created_at = Column(DateTime, default=datetime.utcnow)


class KnowledgeGraphEntity(Base):
    __tablename__ = "knowledge_graph_entity"
    __table_args__ = (
        UniqueConstraint("task_id", "name", "entity_type", name="uq_kg_entity_task_name_type"),
    )

    entity_id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("task.task_id"), nullable=True, index=True)

    name = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    description = Column(Text)
    source_type = Column(String(50), default="agent")
    source_ref = Column(String(500))
    confidence = Column(Float, default=0.7)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeGraphRelation(Base):
    __tablename__ = "knowledge_graph_relation"
    __table_args__ = (
        UniqueConstraint("task_id", "source_name", "target_name", "relation_type", name="uq_kg_relation_task_triple"),
    )

    relation_id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("task.task_id"), nullable=True, index=True)

    source_name = Column(String(255), nullable=False, index=True)
    source_type = Column(String(50), nullable=False)
    target_name = Column(String(255), nullable=False, index=True)
    target_type = Column(String(50), nullable=False)
    relation_type = Column(String(80), nullable=False, index=True)

    evidence = Column(Text)
    source_ref = Column(String(500))
    confidence = Column(Float, default=0.7)

    created_at = Column(DateTime, default=datetime.utcnow)
