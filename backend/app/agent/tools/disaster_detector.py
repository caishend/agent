"""Lightweight disaster object detection for uploaded imagery.

The detector is intentionally dependency-light: it works with Pillow only, so the
project can run without downloading model weights. It exposes the same kind of
structured output a trained detector would return: class label, confidence,
bounding box, area ratio, and an annotated image.
"""
from __future__ import annotations

import sys
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


PixelPredicate = Callable[[int, int, int], bool]


@dataclass(frozen=True)
class DisasterClass:
    label: str
    name: str
    color: tuple[int, int, int]
    predicate: PixelPredicate


class DisasterObjectDetector:
    """Pillow-based disaster detector with YOLO-like structured results."""

    def __init__(
        self,
        *,
        min_area_ratio: float = 0.0015,
        max_detections_per_class: int = 8,
        scope: str = "all",
    ):
        self.min_area_ratio = max(0.0, min_area_ratio)
        self.max_detections_per_class = max(1, max_detections_per_class)
        self.scope = scope
        self.classes = self._classes()

    def detect(self, image: Any, *, mode: str = "flood") -> list[dict[str, Any]]:
        rgb = image.convert("RGB")
        width, height = rgb.size
        pixels = list(rgb.getdata())
        min_pixels = max(12, int(width * height * self.min_area_ratio))
        detections: list[dict[str, Any]] = []

        for disaster_class in self._selected_classes(mode):
            flags = bytearray(
                1 if disaster_class.predicate(red, green, blue) else 0
                for red, green, blue in pixels
            )
            components = self._components(flags, width, height, min_pixels)
            components.sort(key=lambda item: item["area_pixels"], reverse=True)

            for component in components[: self.max_detections_per_class]:
                area_ratio = component["area_pixels"] / max(width * height, 1)
                density = component["area_pixels"] / max(component["bbox_area"], 1)
                confidence = self._confidence(area_ratio, density, disaster_class.label)
                detections.append(
                    {
                        "label": disaster_class.label,
                        "class_name": disaster_class.name,
                        "confidence": confidence,
                        "bbox": component["bbox"],
                        "bbox_normalized": self._normalize_bbox(component["bbox"], width, height),
                        "area_pixels": component["area_pixels"],
                        "area_ratio": area_ratio,
                        "density": density,
                        "detector": "pillow_connected_component_disaster_detector_v1",
                    }
                )

        detections.sort(key=lambda item: item["confidence"], reverse=True)
        return detections

    def write_annotated_image(
        self,
        ImageDraw: Any,
        image: Any,
        detections: list[dict[str, Any]],
        source_path: Path,
        output_dir: Path,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        annotated = image.convert("RGB").copy()
        draw = ImageDraw.Draw(annotated)
        color_by_label = {item.label: item.color for item in self.classes}

        for detection in detections:
            color = color_by_label.get(detection["label"], (255, 0, 0))
            bbox = detection["bbox"]
            draw.rectangle(bbox, outline=color, width=3)
            text = f"{detection['label']} {detection['confidence']:.2f}"
            text_bbox = draw.textbbox((bbox[0], bbox[1]), text)
            background = (text_bbox[0], text_bbox[1], text_bbox[2] + 4, text_bbox[3] + 4)
            draw.rectangle(background, fill=color)
            draw.text((bbox[0] + 2, bbox[1] + 2), text, fill=(255, 255, 255))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"{source_path.stem}_{timestamp}_detections.png"
        annotated.save(output_path)
        return output_path

    def _selected_classes(self, mode: str) -> list[DisasterClass]:
        if self.scope == "mode":
            labels_by_mode = {
                "flood": {"flood_water"},
                "fire": {"active_fire", "burn_scar"},
                "landslide": {"landslide_soil"},
            }
            labels = labels_by_mode.get(mode, {item.label for item in self.classes})
            return [item for item in self.classes if item.label in labels]
        return self.classes

    def _components(
        self,
        flags: bytearray,
        width: int,
        height: int,
        min_pixels: int,
    ) -> list[dict[str, Any]]:
        visited = bytearray(len(flags))
        components: list[dict[str, Any]] = []

        for start, is_target in enumerate(flags):
            if not is_target or visited[start]:
                continue

            queue: deque[int] = deque([start])
            visited[start] = 1
            count = 0
            min_x = width
            min_y = height
            max_x = 0
            max_y = 0

            while queue:
                index = queue.popleft()
                y, x = divmod(index, width)
                count += 1
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

                for neighbor in self._neighbors(index, x, y, width, height):
                    if flags[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        queue.append(neighbor)

            bbox_area = (max_x - min_x + 1) * (max_y - min_y + 1)
            if count >= min_pixels:
                components.append(
                    {
                        "bbox": [min_x, min_y, max_x, max_y],
                        "bbox_area": bbox_area,
                        "area_pixels": count,
                    }
                )

        return components

    def _neighbors(self, index: int, x: int, y: int, width: int, height: int) -> tuple[int, ...]:
        neighbors: list[int] = []
        if x > 0:
            neighbors.append(index - 1)
        if x < width - 1:
            neighbors.append(index + 1)
        if y > 0:
            neighbors.append(index - width)
        if y < height - 1:
            neighbors.append(index + width)
        return tuple(neighbors)

    def _confidence(self, area_ratio: float, density: float, label: str) -> float:
        base_by_label = {
            "active_fire": 0.66,
            "burn_scar": 0.58,
            "flood_water": 0.60,
            "landslide_soil": 0.56,
        }
        base = base_by_label.get(label, 0.55)
        confidence = base + min(0.18, area_ratio * 6.0) + min(0.16, density * 0.18)
        return round(max(0.05, min(confidence, 0.94)), 2)

    def _normalize_bbox(self, bbox: list[int], width: int, height: int) -> list[float]:
        return [
            round(bbox[0] / max(width, 1), 4),
            round(bbox[1] / max(height, 1), 4),
            round(bbox[2] / max(width, 1), 4),
            round(bbox[3] / max(height, 1), 4),
        ]

    def _classes(self) -> list[DisasterClass]:
        return [
            DisasterClass("flood_water", "flood water / inundation", (35, 120, 255), self._is_water),
            DisasterClass("active_fire", "active fire hotspot", (255, 80, 20), self._is_active_fire),
            DisasterClass("burn_scar", "burn scar / charred area", (80, 40, 40), self._is_burn_scar),
            DisasterClass("landslide_soil", "landslide / exposed soil", (190, 125, 55), self._is_landslide_soil),
        ]

    def _is_water(self, red: int, green: int, blue: int) -> bool:
        blue_water = blue > 70 and blue >= green * 0.95 and blue >= red * 1.15 and (blue - red) > 15
        dark_water = red < 65 and green < 85 and blue < 105 and blue >= red * 0.85
        cyan_water = green > 80 and blue > 90 and red < 95 and abs(green - blue) < 60
        return blue_water or dark_water or cyan_water

    def _is_active_fire(self, red: int, green: int, blue: int) -> bool:
        return red > 165 and green > 55 and blue < 90 and red > green * 1.25

    def _is_burn_scar(self, red: int, green: int, blue: int) -> bool:
        dark_char = red < 80 and green < 75 and blue < 75 and abs(red - green) < 25 and abs(green - blue) < 25
        ash_gray = 65 <= red <= 130 and 60 <= green <= 130 and 55 <= blue <= 130 and max(red, green, blue) - min(red, green, blue) < 22
        return dark_char or ash_gray

    def _is_landslide_soil(self, red: int, green: int, blue: int) -> bool:
        brown = red > 95 and green > 70 and blue < 95 and red >= green and green >= blue
        bright_soil = red > 130 and green > 105 and blue > 75 and red > blue * 1.2
        return brown or bright_soil


class DisasterModelUnavailable(RuntimeError):
    """Raised when the migrated disaster model cannot be loaded or executed."""


class DisasterPipelineDetector:
    """Adapter for the migrated multi-expert disaster recognition pipeline.

    The model project under ``disaster/`` owns the heavy dependencies and
    weights. This adapter keeps those imports lazy so the Agent can still boot
    and run tests when torch/ultralytics/transformers are not installed.
    """

    detector_name = "disaster_pipeline_multiexpert_v1"
    _lock = threading.Lock()
    _pipeline_by_key: dict[tuple[str, str | None, float | None], Any] = {}
    _load_errors: dict[tuple[str, str | None, float | None], str] = {}

    def __init__(
        self,
        *,
        model_dir: str | Path | None = None,
        device: str | None = None,
        gate_threshold: float | None = None,
    ):
        self.model_dir = self._resolve_model_dir(model_dir)
        self.device = device
        self.gate_threshold = gate_threshold

    def analyze(self, image_path: Path, output_dir: Path) -> dict[str, Any]:
        pipeline = self._pipeline()
        output_dir.mkdir(parents=True, exist_ok=True)
        visual_dir = output_dir / f"{image_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_model"

        try:
            from PIL import Image
        except ImportError as exc:
            raise DisasterModelUnavailable(f"missing Pillow dependency: {exc}") from exc

        try:
            with Image.open(image_path) as image:
                width, height = image.size
            raw_result = pipeline.run(image_path)
            visual_paths = [str(path) for path in pipeline.visualize(image_path, raw_result, visual_dir)]
        except Exception as exc:  # noqa: BLE001 - convert model failures into fallback signal
            raise DisasterModelUnavailable(str(exc)) from exc

        detections = self._parse_detections(raw_result.get("snow"), width, height)
        segmentations = self._parse_segmentations(raw_result)
        affected = self._affected_summary(detections, segmentations)
        confidence = self._confidence(raw_result.get("gate"), detections, segmentations)
        representative_path = visual_paths[0] if visual_paths else str(image_path)

        return {
            "model_status": "ok",
            "image_path": str(image_path),
            "width": width,
            "height": height,
            "analysis_width": width,
            "analysis_height": height,
            "affected_class": affected["class"],
            "affected_class_name": affected["class_name"],
            "affected_pixels": affected["pixels"],
            "total_pixels": max(width * height, 1),
            "affected_ratio": affected["ratio"],
            "area_km2": None,
            "confidence": confidence,
            "overlay_path": representative_path,
            "detection_path": representative_path,
            "method": self.detector_name,
            "detector": self.detector_name,
            "detections": detections,
            "segmentations": segmentations,
            "class_ratios": {item["class_name"]: item["pixel_ratio"] for item in segmentations},
            "gate": raw_result.get("gate", {}),
            "visualizations": visual_paths,
        }

    def preload(self) -> None:
        self._pipeline()

    def _pipeline(self) -> Any:
        key = (str(self.model_dir), self.device, self.gate_threshold)
        if key in self._load_errors:
            raise DisasterModelUnavailable(self._load_errors[key])
        if key in self._pipeline_by_key:
            return self._pipeline_by_key[key]

        with self._lock:
            if key in self._load_errors:
                raise DisasterModelUnavailable(self._load_errors[key])
            if key in self._pipeline_by_key:
                return self._pipeline_by_key[key]

            try:
                if not self.model_dir.exists():
                    raise FileNotFoundError(f"model directory not found: {self.model_dir}")
                if str(self.model_dir) not in sys.path:
                    sys.path.insert(0, str(self.model_dir))
                from pipeline.pipeline import DisasterPipeline

                pipeline = DisasterPipeline(device=self.device, gate_threshold=self.gate_threshold)
            except Exception as exc:  # noqa: BLE001 - cache load error for cheap fallback
                self._load_errors[key] = str(exc)
                raise DisasterModelUnavailable(str(exc)) from exc

            self._pipeline_by_key[key] = pipeline
            return pipeline

    def _resolve_model_dir(self, model_dir: str | Path | None) -> Path:
        if model_dir:
            path = Path(model_dir).expanduser()
            if not path.is_absolute():
                path = self._repo_root() / path
            return path.resolve()
        return (self._repo_root() / "disaster").resolve()

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[4]

    def _parse_detections(self, snow_raw: dict[str, Any] | None, width: int, height: int) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for detection in (snow_raw or {}).get("detections", []):
            bbox = [float(value) for value in detection.get("box_xyxy", [])[:4]]
            if len(bbox) != 4:
                continue
            x1, y1, x2, y2 = bbox
            area_pixels = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            bbox_area = max(area_pixels, 1.0)
            parsed.append(
                {
                    "label": str(detection.get("class_name") or detection.get("class_id") or "unknown"),
                    "class_name": str(detection.get("class_name") or "unknown"),
                    "confidence": float(detection.get("confidence") or 0.0),
                    "bbox": [round(value, 1) for value in bbox],
                    "bbox_normalized": self._normalize_bbox(bbox, width, height),
                    "area_pixels": int(area_pixels),
                    "area_ratio": area_pixels / max(width * height, 1),
                    "density": area_pixels / bbox_area,
                    "detector": self.detector_name,
                }
            )
        parsed.sort(key=lambda item: item["confidence"], reverse=True)
        return parsed

    def _parse_segmentations(self, raw_result: dict[str, Any]) -> list[dict[str, Any]]:
        segmentations: list[dict[str, Any]] = []
        for source_name in ("vitseg", "segformer"):
            raw = raw_result.get(source_name)
            if not raw:
                continue
            counts = raw.get("pixel_counts", {})
            ratios = raw.get("pixel_ratios", {})
            for class_name, pixel_count in counts.items():
                if class_name == "background" or int(pixel_count) <= 0:
                    continue
                segmentations.append(
                    {
                        "source": source_name,
                        "class_name": str(class_name),
                        "pixel_count": int(pixel_count),
                        "pixel_ratio": float(ratios.get(class_name) or 0.0),
                    }
                )
        segmentations.sort(key=lambda item: item["pixel_ratio"], reverse=True)
        return segmentations

    def _affected_summary(
        self,
        detections: list[dict[str, Any]],
        segmentations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if segmentations:
            dominant = segmentations[0]
            pixels = sum(item["pixel_count"] for item in segmentations)
            ratio = min(1.0, sum(item["pixel_ratio"] for item in segmentations))
            return {
                "class": dominant["class_name"],
                "class_name": self._display_name(dominant["class_name"]),
                "pixels": pixels,
                "ratio": ratio,
            }
        if detections:
            dominant = detections[0]
            ratio = min(1.0, sum(item["area_ratio"] for item in detections))
            return {
                "class": dominant["class_name"],
                "class_name": self._display_name(dominant["class_name"]),
                "pixels": sum(item["area_pixels"] for item in detections),
                "ratio": ratio,
            }
        return {"class": "none", "class_name": "no routed disaster target", "pixels": 0, "ratio": 0.0}

    def _confidence(
        self,
        gate_raw: dict[str, Any] | None,
        detections: list[dict[str, Any]],
        segmentations: list[dict[str, Any]],
    ) -> float:
        values = [item["confidence"] for item in detections]
        values.extend(min(0.95, 0.55 + item["pixel_ratio"]) for item in segmentations)
        probabilities = (gate_raw or {}).get("probabilities", {})
        values.extend(float(value) for value in probabilities.values())
        return round(max(values) if values else 0.5, 2)

    def _normalize_bbox(self, bbox: list[float], width: int, height: int) -> list[float]:
        return [
            round(bbox[0] / max(width, 1), 4),
            round(bbox[1] / max(height, 1), 4),
            round(bbox[2] / max(width, 1), 4),
            round(bbox[3] / max(height, 1), 4),
        ]

    def _display_name(self, class_name: str) -> str:
        return {
            "snow": "snow",
            "water_accumulation": "water accumulation",
            "flood": "flood",
            "landslide": "landslide",
            "crack": "crack",
            "rockfall": "rockfall",
            "sinkhole": "sinkhole",
            "debris_flow": "debris flow",
            "pipe": "pipe",
            "construction_area": "construction area",
        }.get(class_name, class_name)
