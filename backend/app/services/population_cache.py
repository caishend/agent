from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.overview import AdminPopulationStat, PopulationRasterSample
from app.services.local_geodata import (
    _population_image,
    _population_metadata,
    load_china_province_geojson,
    population_dataset_status,
)

DEFAULT_YEAR = 2025


def population_cache_status(db: Session) -> dict[str, Any]:
    sample_count = db.query(PopulationRasterSample).filter(PopulationRasterSample.year == DEFAULT_YEAR).count()
    admin_count = db.query(AdminPopulationStat).filter(AdminPopulationStat.year == DEFAULT_YEAR).count()
    return {
        "available": sample_count > 0,
        "sample_count": sample_count,
        "admin_count": admin_count,
        "year": DEFAULT_YEAR,
        "data_source": "mysql:population_raster_sample/admin_population_stat",
    }


def heatmap_points_from_db(db: Session, limit: int = 3500) -> list[list[float]]:
    rows = (
        db.query(PopulationRasterSample)
        .filter(PopulationRasterSample.year == DEFAULT_YEAR)
        .order_by(PopulationRasterSample.density_per_km2.desc())
        .limit(limit)
        .all()
    )
    return [[row.longitude, row.latitude, round(row.density_per_km2 or row.population_value or 0, 3)] for row in rows]


def admin_population_rows(db: Session, limit: int = 12) -> list[AdminPopulationStat]:
    return (
        db.query(AdminPopulationStat)
        .filter(AdminPopulationStat.year == DEFAULT_YEAR)
        .order_by(AdminPopulationStat.density_per_km2.desc())
        .limit(limit)
        .all()
    )


def estimate_population_exposure_from_db(
    db: Session,
    longitude: float | None,
    latitude: float | None,
    radius_km: float,
) -> dict[str, Any]:
    if longitude is None or latitude is None or radius_km <= 0:
        return {"available": False, "estimated_population": 0, "reason": "missing_or_invalid_location"}

    delta_lat = radius_km / 111.32
    delta_lng = radius_km / max(1.0, 111.32 * math.cos(math.radians(latitude)))
    rows = (
        db.query(PopulationRasterSample)
        .filter(
            PopulationRasterSample.year == DEFAULT_YEAR,
            PopulationRasterSample.longitude >= longitude - delta_lng,
            PopulationRasterSample.longitude <= longitude + delta_lng,
            PopulationRasterSample.latitude >= latitude - delta_lat,
            PopulationRasterSample.latitude <= latitude + delta_lat,
        )
        .all()
    )
    if not rows:
        return {"available": False, "estimated_population": 0, "reason": "population_cache_miss"}

    nearby = [
        row
        for row in rows
        if _haversine_km(longitude, latitude, row.longitude, row.latitude) <= radius_km
    ]
    if not nearby:
        return {"available": False, "estimated_population": 0, "reason": "population_cache_no_nearby_sample"}

    mean_density = sum(float(row.density_per_km2 or 0) for row in nearby) / len(nearby)
    area_km2 = math.pi * radius_km * radius_km
    estimated_population = int(mean_density * area_km2)
    return {
        "available": True,
        "estimated_population": max(0, estimated_population),
        "sampled_cells": len(nearby),
        "radius_km": radius_km,
        "area_km2": round(area_km2, 2),
        "mean_density_per_km2": round(mean_density, 2),
        "data_source": "MySQL preprocessed population raster samples",
    }


def preprocess_population_cache(
    db: Session,
    stride_pixels: int = 520,
    max_samples: int = 7000,
    reset: bool = False,
) -> dict[str, Any]:
    if reset:
        db.query(PopulationRasterSample).filter(PopulationRasterSample.year == DEFAULT_YEAR).delete()
        db.query(AdminPopulationStat).filter(AdminPopulationStat.year == DEFAULT_YEAR).delete()
        db.commit()

    existing = db.query(PopulationRasterSample).filter(PopulationRasterSample.year == DEFAULT_YEAR).count()
    if existing:
        return {"created": False, **population_cache_status(db)}

    dataset = population_dataset_status()
    if not dataset.get("available"):
        return {"created": False, "available": False, "reason": dataset.get("error") or dataset.get("path")}

    metadata = _population_metadata()
    image = _population_image()
    province_features = _province_features()
    cell_area_km2 = _cell_area_km2(metadata)
    samples: list[PopulationRasterSample] = []
    admin_groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"population": 0.0, "density_sum": 0.0, "count": 0})

    for y in range(0, metadata["height"], stride_pixels):
        latitude = metadata["origin_lat"] - y * metadata["pixel_height"]
        if latitude < 17 or latitude > 54:
            continue
        for x in range(0, metadata["width"], stride_pixels):
            longitude = metadata["origin_lng"] + x * metadata["pixel_width"]
            if longitude < 72 or longitude > 136:
                continue
            value = float(image.getpixel((x, y)))
            if value <= 0 or value == metadata["nodata"] or not math.isfinite(value):
                continue

            density = value / max(cell_area_km2, 0.0001)
            province = _find_province_name(longitude, latitude, province_features)
            samples.append(
                PopulationRasterSample(
                    longitude=round(longitude, 5),
                    latitude=round(latitude, 5),
                    population_value=value,
                    density_per_km2=round(density, 3),
                    province=province,
                    year=DEFAULT_YEAR,
                )
            )
            if province:
                group = admin_groups[province]
                group["population"] += value * stride_pixels * stride_pixels
                group["density_sum"] += density
                group["count"] += 1

    samples.sort(key=lambda item: item.density_per_km2 or 0, reverse=True)
    db.bulk_save_objects(samples[:max_samples])
    _upsert_admin_stats(db, admin_groups)
    db.commit()
    return {"created": True, **population_cache_status(db)}


def _upsert_admin_stats(db: Session, groups: dict[str, dict[str, Any]]) -> None:
    for name, stats in groups.items():
        if stats["count"] <= 0:
            continue
        row = (
            db.query(AdminPopulationStat)
            .filter(
                AdminPopulationStat.admin_level == "province",
                AdminPopulationStat.admin_name == name,
                AdminPopulationStat.year == DEFAULT_YEAR,
            )
            .first()
        )
        if not row:
            row = AdminPopulationStat(admin_level="province", admin_name=name, year=DEFAULT_YEAR)
            db.add(row)
        row.population = int(stats["population"])
        row.density_per_km2 = round(stats["density_sum"] / stats["count"], 2)
        row.sample_count = int(stats["count"])
        row.data_source = "local_worldpop_geotiff_preprocessed"
        row.updated_at = datetime.utcnow()


def _province_features() -> list[dict[str, Any]]:
    features = []
    for feature in load_china_province_geojson().get("features", []):
        geometry = feature.get("geometry") or {}
        bbox = _geometry_bbox(geometry)
        if bbox:
            features.append(
                {
                    "name": _feature_name(feature),
                    "geometry": geometry,
                    "bbox": bbox,
                }
            )
    return features


def _feature_name(feature: dict[str, Any]) -> str:
    properties = feature.get("properties") or {}
    return str(
        properties.get("NAME")
        or properties.get("name")
        or properties.get("省")
        or properties.get("province")
        or properties.get("ADCODE99")
        or properties.get("ADCODE93")
        or "unknown"
    )


def _find_province_name(longitude: float, latitude: float, features: list[dict[str, Any]]) -> str | None:
    for feature in features:
        min_lng, min_lat, max_lng, max_lat = feature["bbox"]
        if not (min_lng <= longitude <= max_lng and min_lat <= latitude <= max_lat):
            continue
        if _geometry_contains(feature["geometry"], longitude, latitude):
            return feature["name"]
    return None


def _geometry_contains(geometry: dict[str, Any], longitude: float, latitude: float) -> bool:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        return any(_ring_contains(ring, longitude, latitude) for ring in coordinates[:1])
    if geometry_type == "MultiPolygon":
        return any(any(_ring_contains(ring, longitude, latitude) for ring in polygon[:1]) for polygon in coordinates)
    return False


def _ring_contains(ring: list[list[float]], longitude: float, latitude: float) -> bool:
    inside = False
    previous_lng, previous_lat = ring[-1]
    for current_lng, current_lat in ring:
        crosses = (current_lat > latitude) != (previous_lat > latitude)
        if crosses:
            intersect_lng = (previous_lng - current_lng) * (latitude - current_lat) / ((previous_lat - current_lat) or 1e-12) + current_lng
            if longitude < intersect_lng:
                inside = not inside
        previous_lng, previous_lat = current_lng, current_lat
    return inside


def _geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    points = list(_iter_geometry_points(geometry.get("coordinates") or []))
    if not points:
        return None
    lngs = [point[0] for point in points]
    lats = [point[1] for point in points]
    return min(lngs), min(lats), max(lngs), max(lats)


def _iter_geometry_points(coordinates):
    if not coordinates:
        return
    first = coordinates[0]
    if isinstance(first, (int, float)):
        yield coordinates
        return
    for item in coordinates:
        yield from _iter_geometry_points(item)


def _cell_area_km2(metadata: dict[str, Any]) -> float:
    mean_latitude = 35.0
    return (metadata["pixel_height"] * 111.32) * (metadata["pixel_width"] * 111.32 * math.cos(math.radians(mean_latitude)))


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    radius = 6371.0088
    delta_lng = math.radians(lng2 - lng1)
    delta_lat = math.radians(lat2 - lat1)
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))
