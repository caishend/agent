from __future__ import annotations

from copy import deepcopy
from typing import Callable, Iterable

import cv2
import numpy as np


MIN_CONFIDENCE = 0.60
HIGH_CONFIDENCE = 0.85
SMALL_AREA_RATIO = 0.03
EDGE_MARGIN_RATIO = 0.05
TOP_REGION_RATIO = 0.15
SMALL_COMPONENT_OF_MAX = 0.05
DOMINANT_RATIO = 0.80
DOMINANT_FOREGROUND_RATIO = 0.90
MINOR_RATIO = 0.05
TINY_RATIO = 0.03
THIN_ASPECT_RATIO = 12.0

EXCLUSIVE_PAIRS = (
    ("rockfall", "landslide"),
    ("crack", "sinkhole"),
    ("debris_flow", "landslide"),
    ("flood", "water_accumulation"),
    ("ice", "snowmelt_water"),
    ("frozen", "snowmelt_water"),
    ("fire", "smoke"),
)


def postprocess_outputs(
    image_size: tuple[int, int],
    snow_raw: dict | None,
    vitseg_raw: dict | None,
    segformer_raw: dict | None,
    vitseg_classes: list[str],
    segformer_classes: list[str],
) -> tuple[dict | None, dict | None, dict | None]:
    """Clean expert outputs before visualization and API serialization."""
    snow_clean = _postprocess_detections(snow_raw, image_size)
    vitseg_clean = _postprocess_segmentation(vitseg_raw, vitseg_classes)
    segformer_clean = _postprocess_segmentation(segformer_raw, segformer_classes)
    return snow_clean, vitseg_clean, segformer_clean


def _postprocess_detections(raw: dict | None, image_size: tuple[int, int]) -> dict | None:
    if raw is None:
        return None

    img_w, img_h = image_size
    image_area = max(1, img_w * img_h)
    detections = []

    copied = deepcopy(raw)
    source = copied.get("detections", [])
    main_conf = max((_to_float(det.get("confidence")) for det in source), default=0.0)

    for det in source:
        conf = _to_float(det.get("confidence"))
        if conf < MIN_CONFIDENCE:
            continue

        box = _clamp_box(det.get("box_xyxy"), img_w, img_h)
        if box is None:
            continue

        x1, y1, x2, y2 = box
        box_area = max(0.0, (x2 - x1) * (y2 - y1))
        area_ratio = box_area / image_area

        if area_ratio < SMALL_AREA_RATIO and _is_top_or_edge(x1, y1, x2, y2, img_w, img_h):
            continue

        if main_conf >= HIGH_CONFIDENCE and conf <= main_conf - 0.25 and area_ratio < MINOR_RATIO:
            continue

        if _is_extremely_thin(x2 - x1, y2 - y1) and area_ratio < MINOR_RATIO and conf < HIGH_CONFIDENCE:
            continue

        cleaned = dict(det)
        cleaned["confidence"] = round(conf, 4)
        cleaned["box_xyxy"] = [round(v, 1) for v in box]
        cleaned["_area_ratio"] = area_ratio
        detections.append(cleaned)

    detections = _suppress_detection_class_conflicts(detections)
    for det in detections:
        det.pop("_area_ratio", None)

    copied["detections"] = detections
    return copied


def _postprocess_segmentation(raw: dict | None, class_names: list[str]) -> dict | None:
    if raw is None or "mask" not in raw:
        return raw

    copied = deepcopy(raw)
    mask = np.asarray(copied["mask"]).astype(np.uint8)
    bg_id = _background_id(class_names)
    cleaned = np.full(mask.shape, bg_id, dtype=np.uint8)
    image_area = max(1, mask.size)

    for cls_id, class_name in enumerate(class_names):
        if cls_id == bg_id:
            continue

        binary = (mask == cls_id).astype(np.uint8)
        if int(binary.sum()) == 0:
            continue

        preserve_thin = class_name == "crack"
        binary = _smooth_binary_mask(binary, preserve_thin=preserve_thin)
        binary = _keep_reasonable_components(binary, image_area, preserve_thin=preserve_thin)
        if int(binary.sum()) == 0:
            continue

        cleaned[binary == 1] = cls_id

    cleaned = _suppress_segmentation_class_conflicts(cleaned, class_names, bg_id)
    cleaned = _smooth_label_boundaries(cleaned, class_names, bg_id)
    copied["mask"] = cleaned.astype(np.uint8)
    _refresh_segmentation_stats(copied, class_names)
    return copied


def _smooth_binary_mask(binary: np.ndarray, preserve_thin: bool) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    if preserve_thin:
        return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)


def _keep_reasonable_components(binary: np.ndarray, image_area: int, preserve_thin: bool) -> np.ndarray:
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if num_labels <= 1:
        return np.zeros_like(binary, dtype=np.uint8)

    areas = stats[1:, cv2.CC_STAT_AREA]
    max_area = int(areas.max(initial=0))
    if max_area <= 0:
        return np.zeros_like(binary, dtype=np.uint8)

    h, w = binary.shape
    kept = np.zeros_like(binary, dtype=np.uint8)
    kept_labels = []

    for label in range(1, num_labels):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < max_area * SMALL_COMPONENT_OF_MAX:
            continue

        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        bw = int(stats[label, cv2.CC_STAT_WIDTH])
        bh = int(stats[label, cv2.CC_STAT_HEIGHT])
        area_ratio = area / image_area

        if area_ratio < SMALL_AREA_RATIO and _is_top_or_edge(x, y, x + bw, y + bh, w, h):
            continue

        if not preserve_thin and _is_extremely_thin(bw, bh) and area_ratio < MINOR_RATIO:
            continue

        kept[labels == label] = 1
        kept_labels.append(label)

    if len(kept_labels) > 4 and int(kept.sum()) / image_area < 0.10:
        largest_label = max(kept_labels, key=lambda label: int(stats[label, cv2.CC_STAT_AREA]))
        largest_only = np.zeros_like(binary, dtype=np.uint8)
        largest_only[labels == largest_label] = 1
        return largest_only

    return kept


def _suppress_detection_class_conflicts(detections: list[dict]) -> list[dict]:
    if not detections:
        return detections

    detections = _suppress_class_pairs(
        detections,
        get_name=lambda det: str(det.get("class_name", "")),
        get_ratio=lambda det: float(det.get("_area_ratio", 0.0)),
        get_conf=lambda det: _to_float(det.get("confidence")),
    )

    stats = _class_stats(
        detections,
        get_name=lambda det: str(det.get("class_name", "")),
        get_ratio=lambda det: float(det.get("_area_ratio", 0.0)),
        get_conf=lambda det: _to_float(det.get("confidence")),
    )
    if not stats:
        return detections

    dominant_name, dominant = max(stats.items(), key=lambda item: item[1]["ratio"])
    if dominant["ratio"] >= DOMINANT_FOREGROUND_RATIO:
        detections = [
            det for det in detections
            if str(det.get("class_name", "")) == dominant_name
            or stats.get(str(det.get("class_name", "")), {}).get("ratio", 0.0) >= TINY_RATIO
            or _to_float(det.get("confidence")) >= HIGH_CONFIDENCE
        ]

    return detections


def _suppress_segmentation_class_conflicts(
    mask: np.ndarray,
    class_names: list[str],
    bg_id: int,
) -> np.ndarray:
    total = max(1, mask.size)
    ratios = {
        name: float((mask == cls_id).sum()) / total
        for cls_id, name in enumerate(class_names)
        if cls_id != bg_id
    }

    for first, second in EXCLUSIVE_PAIRS:
        if first not in class_names or second not in class_names:
            continue
        first_ratio = ratios.get(first, 0.0)
        second_ratio = ratios.get(second, 0.0)
        first_id = class_names.index(first)
        second_id = class_names.index(second)

        if first_ratio > DOMINANT_RATIO and second_ratio < MINOR_RATIO:
            mask[mask == second_id] = bg_id
            ratios[second] = 0.0
        elif second_ratio > DOMINANT_RATIO and first_ratio < MINOR_RATIO:
            mask[mask == first_id] = bg_id
            ratios[first] = 0.0

    foreground_total = sum(
        int((mask == cls_id).sum())
        for cls_id, name in enumerate(class_names)
        if cls_id != bg_id
    )
    if foreground_total <= 0:
        return mask

    foreground_ratios = {
        name: int((mask == cls_id).sum()) / foreground_total
        for cls_id, name in enumerate(class_names)
        if cls_id != bg_id
    }
    dominant_name, dominant_ratio = max(foreground_ratios.items(), key=lambda item: item[1])
    if dominant_ratio >= DOMINANT_FOREGROUND_RATIO:
        for cls_id, name in enumerate(class_names):
            if cls_id == bg_id or name == dominant_name:
                continue
            if foreground_ratios.get(name, 0.0) < TINY_RATIO:
                mask[mask == cls_id] = bg_id

    return mask


def _smooth_label_boundaries(mask: np.ndarray, class_names: list[str], bg_id: int) -> np.ndarray:
    final = np.full(mask.shape, bg_id, dtype=np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    for cls_id, name in enumerate(class_names):
        if cls_id == bg_id:
            continue
        binary = (mask == cls_id).astype(np.uint8)
        if int(binary.sum()) == 0:
            continue
        if name == "crack":
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        else:
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        final[binary == 1] = cls_id

    return final


def _refresh_segmentation_stats(raw: dict, class_names: list[str]) -> None:
    mask = np.asarray(raw["mask"])
    total = max(1, mask.size)
    counts = {name: int((mask == idx).sum()) for idx, name in enumerate(class_names)}
    raw["pixel_counts"] = counts
    raw["pixel_ratios"] = {name: round(count / total, 4) for name, count in counts.items()}


def _suppress_class_pairs(
    items: list[dict],
    get_name: Callable[[dict], str],
    get_ratio: Callable[[dict], float],
    get_conf: Callable[[dict], float],
) -> list[dict]:
    stats = _class_stats(items, get_name, get_ratio, get_conf)
    removed: set[str] = set()

    for first, second in EXCLUSIVE_PAIRS:
        if first not in stats or second not in stats:
            continue
        first_stats = stats[first]
        second_stats = stats[second]

        if first_stats["ratio"] > DOMINANT_RATIO and second_stats["ratio"] < MINOR_RATIO:
            removed.add(second)
        elif second_stats["ratio"] > DOMINANT_RATIO and first_stats["ratio"] < MINOR_RATIO:
            removed.add(first)
        elif first_stats["ratio"] < TINY_RATIO and second_stats["confidence"] > first_stats["confidence"]:
            removed.add(first)
        elif second_stats["ratio"] < TINY_RATIO and first_stats["confidence"] > second_stats["confidence"]:
            removed.add(second)

    if not removed:
        return items
    return [item for item in items if get_name(item) not in removed]


def _class_stats(
    items: Iterable[dict],
    get_name: Callable[[dict], str],
    get_ratio: Callable[[dict], float],
    get_conf: Callable[[dict], float],
) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    for item in items:
        name = get_name(item)
        if not name:
            continue
        cls = stats.setdefault(name, {"ratio": 0.0, "confidence": 0.0})
        cls["ratio"] += max(0.0, get_ratio(item))
        cls["confidence"] = max(cls["confidence"], get_conf(item))
    return stats


def _background_id(class_names: list[str]) -> int:
    try:
        return class_names.index("background")
    except ValueError:
        return 0


def _clamp_box(box: object, img_w: int, img_h: int) -> tuple[float, float, float, float] | None:
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return None
    x1, y1, x2, y2 = (_to_float(value) for value in box[:4])
    x1 = min(max(x1, 0.0), float(img_w))
    x2 = min(max(x2, 0.0), float(img_w))
    y1 = min(max(y1, 0.0), float(img_h))
    y2 = min(max(y2, 0.0), float(img_h))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _is_top_or_edge(x1: float, y1: float, x2: float, y2: float, img_w: int, img_h: int) -> bool:
    edge_x = img_w * EDGE_MARGIN_RATIO
    edge_y = img_h * EDGE_MARGIN_RATIO
    in_top = y1 <= img_h * TOP_REGION_RATIO
    near_edge = x1 <= edge_x or y1 <= edge_y or x2 >= img_w - edge_x or y2 >= img_h - edge_y
    return in_top or near_edge


def _is_extremely_thin(width: float, height: float) -> bool:
    if width <= 0 or height <= 0:
        return True
    aspect = max(width / height, height / width)
    return aspect >= THIN_ASPECT_RATIO


def _to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
