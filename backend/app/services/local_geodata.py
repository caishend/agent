from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
POPULATION_TIF_NAME = "chn_pop_2025_CN_100m_R2025A_v1.tif"
NODATA_DEFAULT = -99999

CITY_COORDS: dict[str, tuple[float, float]] = {
    "北京": (116.4074, 39.9042),
    "上海": (121.4737, 31.2304),
    "广州": (113.2644, 23.1291),
    "深圳": (114.0579, 22.5431),
    "成都": (104.0668, 30.5728),
    "重庆": (106.5516, 29.5630),
    "武汉": (114.3054, 30.5931),
    "杭州": (120.1551, 30.2741),
    "南京": (118.7969, 32.0603),
    "郑州": (113.6254, 34.7466),
    "西安": (108.9398, 34.3416),
    "天津": (117.2000, 39.0842),
    "福州": (119.2965, 26.0745),
    "厦门": (118.0894, 24.4798),
    "长沙": (112.9388, 28.2282),
    "昆明": (102.8332, 24.8801),
    "贵阳": (106.6302, 26.6470),
    "南宁": (108.3669, 22.8170),
    "海口": (110.3312, 20.0311),
    "兰州": (103.8343, 36.0611),
    "银川": (106.2309, 38.4872),
    "乌鲁木齐": (87.6168, 43.8256),
    "拉萨": (91.1172, 29.6469),
    "青岛": (120.3826, 36.0671),
}


@lru_cache(maxsize=1)
def load_china_province_geojson() -> dict[str, Any]:
    path = _find_geojson("provincialBoundary", "bou2_4p.json")
    if not path:
        return {"type": "FeatureCollection", "features": []}
    return json.loads(path.read_text(encoding="utf-8"))


def population_dataset_status() -> dict[str, Any]:
    path = _population_tif_path()
    if not path.exists():
        return {"available": False, "path": str(path)}
    try:
        metadata = _population_metadata()
        return {
            "available": True,
            "path": str(path),
            "width": metadata["width"],
            "height": metadata["height"],
            "origin_lng": metadata["origin_lng"],
            "origin_lat": metadata["origin_lat"],
            "pixel_width": metadata["pixel_width"],
            "pixel_height": metadata["pixel_height"],
            "data_source": "WorldPop R2025A 100m",
        }
    except Exception as error:
        return {"available": False, "path": str(path), "error": str(error)}


@lru_cache(maxsize=1)
def population_heatmap_points(max_points: int = 2600, stride_pixels: int = 420) -> list[list[float]]:
    path = _population_tif_path()
    if not path.exists():
        return []

    metadata = _population_metadata()
    image = _population_image()
    points: list[list[float]] = []
    nodata = metadata["nodata"]

    for y in range(0, metadata["height"], stride_pixels):
        latitude = metadata["origin_lat"] - y * metadata["pixel_height"]
        if latitude < 17 or latitude > 54:
            continue
        for x in range(0, metadata["width"], stride_pixels):
            longitude = metadata["origin_lng"] + x * metadata["pixel_width"]
            if longitude < 72 or longitude > 136:
                continue
            try:
                value = float(image.getpixel((x, y)))
            except Exception:
                continue
            if value <= 0 or value == nodata or not math.isfinite(value):
                continue
            points.append([round(longitude, 4), round(latitude, 4), round(value, 3)])

    points.sort(key=lambda item: item[2], reverse=True)
    return points[:max_points]


def estimate_population_exposure(
    longitude: float | None,
    latitude: float | None,
    radius_km: float,
) -> dict[str, Any]:
    if longitude is None or latitude is None:
        return {"available": False, "estimated_population": 0, "reason": "缺少经纬度"}
    if radius_km <= 0:
        return {"available": False, "estimated_population": 0, "reason": "影响半径无效"}

    path = _population_tif_path()
    if not path.exists():
        return {"available": False, "estimated_population": 0, "reason": f"未找到人口栅格：{path}"}

    try:
        metadata = _population_metadata()
        center_x, center_y = _lonlat_to_pixel(longitude, latitude, metadata)
        radius_x = max(1, int(radius_km / _km_per_pixel_lon(latitude, metadata["pixel_width"])))
        radius_y = max(1, int(radius_km / _km_per_pixel_lat(metadata["pixel_height"])))

        left = max(0, center_x - radius_x)
        right = min(metadata["width"], center_x + radius_x + 1)
        upper = max(0, center_y - radius_y)
        lower = min(metadata["height"], center_y + radius_y + 1)
        if left >= right or upper >= lower:
            return {"available": False, "estimated_population": 0, "reason": "坐标超出人口栅格范围"}

        window = _population_image().crop((left, upper, right, lower))
        values = np.asarray(window, dtype=np.float64)

        y_indices, x_indices = np.ogrid[upper:lower, left:right]
        lon_values = metadata["origin_lng"] + x_indices * metadata["pixel_width"]
        lat_values = metadata["origin_lat"] - y_indices * metadata["pixel_height"]
        distance_km = _haversine_grid(longitude, latitude, lon_values, lat_values)
        valid_mask = (distance_km <= radius_km) & np.isfinite(values) & (values != metadata["nodata"]) & (values > 0)
        estimated_population = int(np.nansum(values[valid_mask]))
        sampled_cells = int(np.count_nonzero(valid_mask))
        area_km2 = math.pi * radius_km * radius_km

        return {
            "available": True,
            "estimated_population": max(0, estimated_population),
            "sampled_cells": sampled_cells,
            "radius_km": radius_km,
            "area_km2": round(area_km2, 2),
            "mean_density_per_km2": round(estimated_population / area_km2, 2) if area_km2 else None,
            "data_source": "WorldPop R2025A 100m local GeoTIFF",
        }
    except Exception as error:
        return {"available": False, "estimated_population": 0, "reason": str(error)}


def estimate_population_for_locations(locations: list[str], radius_km: float) -> dict[str, Any]:
    results = []
    total_population = 0
    for location in locations:
        match = _match_city(location)
        if not match:
            continue
        city_name, (longitude, latitude) = match
        estimate = estimate_population_exposure(longitude, latitude, radius_km)
        if estimate.get("available"):
            total_population += int(estimate.get("estimated_population") or 0)
        results.append({"location": city_name, "longitude": longitude, "latitude": latitude, **estimate})
    return {
        "available": any(item.get("available") for item in results),
        "total_exposed_population": total_population,
        "locations": results,
        "radius_km": radius_km,
    }


def _find_geojson(parent_name: str, file_name: str) -> Path | None:
    for path in DATA_DIR.rglob(file_name):
        if parent_name in str(path):
            return path
    return None


def _match_city(location: str) -> tuple[str, tuple[float, float]] | None:
    for city_name, coords in CITY_COORDS.items():
        if city_name in str(location):
            return city_name, coords
    return None


def _population_tif_path() -> Path:
    return DATA_DIR / POPULATION_TIF_NAME


@lru_cache(maxsize=1)
def _population_metadata() -> dict[str, Any]:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(_population_tif_path()) as image:
        pixel_scale = image.tag_v2.get(33550)
        tiepoint = image.tag_v2.get(33922)
        nodata = image.tag_v2.get(42113, NODATA_DEFAULT)
        if not pixel_scale or not tiepoint:
            raise ValueError("人口 GeoTIFF 缺少 ModelPixelScale 或 ModelTiepoint 标签")
        return {
            "width": image.width,
            "height": image.height,
            "pixel_width": abs(float(pixel_scale[0])),
            "pixel_height": abs(float(pixel_scale[1])),
            "origin_lng": float(tiepoint[3]),
            "origin_lat": float(tiepoint[4]),
            "nodata": float(nodata),
        }


@lru_cache(maxsize=1)
def _population_image():
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    return Image.open(_population_tif_path())


def _lonlat_to_pixel(longitude: float, latitude: float, metadata: dict[str, Any]) -> tuple[int, int]:
    x = int(round((longitude - metadata["origin_lng"]) / metadata["pixel_width"]))
    y = int(round((metadata["origin_lat"] - latitude) / metadata["pixel_height"]))
    return x, y


def _km_per_pixel_lat(pixel_height: float) -> float:
    return pixel_height * 111.32


def _km_per_pixel_lon(latitude: float, pixel_width: float) -> float:
    return max(0.01, pixel_width * 111.32 * math.cos(math.radians(latitude)))


def _haversine_grid(center_lng: float, center_lat: float, lng_grid: np.ndarray, lat_grid: np.ndarray) -> np.ndarray:
    radius = 6371.0088
    lng1 = np.radians(center_lng)
    lat1 = np.radians(center_lat)
    lng2 = np.radians(lng_grid)
    lat2 = np.radians(lat_grid)
    delta_lng = lng2 - lng1
    delta_lat = lat2 - lat1
    a = np.sin(delta_lat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(delta_lng / 2) ** 2
    return 2 * radius * np.arcsin(np.sqrt(a))
