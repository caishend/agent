"""遥感影像分析工具。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.agent.tools.base_tool import ArtifactItem, BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult
from app.agent.tools.disaster_detector import (
    DisasterModelUnavailable,
    DisasterObjectDetector,
    DisasterPipelineDetector,
)


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
IMAGE_PATH_PATTERN = re.compile(r"([A-Za-z]:\\[^\s,;，；]+?\.(?:png|jpg|jpeg|tif|tiff|bmp|webp)|[^\s,;，；:：]+?\.(?:png|jpg|jpeg|tif|tiff|bmp|webp))", re.I)


class RemoteSensingTool(BaseTool):
    name = "remote_sensing"
    description = "对卫星遥感影像进行语义分割，检测灾害区域并估算受影响面积。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        params = tool_input.params or {}
        image_paths, invalid_paths = self._collect_image_paths(tool_input)
        if invalid_paths:
            return self._failed(
                "遥感分析失败：存在不可用的影像路径。",
                "invalid_image_paths",
                invalid_paths=invalid_paths,
            )
        if not image_paths:
            return self._failed(
                "遥感分析失败：请先上传遥感/卫星影像，或在 image_path / image_paths 参数中提供图片路径。",
                "missing_image",
            )

        try:
            from PIL import Image, ImageDraw
        except ImportError as exc:
            return self._failed(
                "遥感分析失败：缺少 pillow 依赖，请先安装 backend/requirements.txt。",
                "missing_dependency",
                error=str(exc),
            )

        mode = self._infer_mode(tool_input.query, params)
        processed_dir = self._processed_dir(context)
        results: list[dict[str, Any]] = []
        artifacts: list[ArtifactItem] = []
        evidence: list[EvidenceItem] = []

        for image_path in image_paths:
            try:
                result = self._analyze_image(Image, ImageDraw, image_path, mode, params, processed_dir)
            except OSError as exc:
                return self._failed(
                    f"遥感分析失败：无法读取影像 {image_path}：{exc}",
                    "image_read_failed",
                    error=str(exc),
                    image_path=str(image_path),
                )

            results.append(result)
            artifacts.append(
                ArtifactItem(
                    type="remote_sensing_overlay",
                    path=result["overlay_path"],
                    metadata={"source_image": str(image_path), "class": result["affected_class"]},
                )
            )
            artifacts.append(
                ArtifactItem(
                    type="object_detection",
                    path=result["detection_path"],
                    metadata={
                        "source_image": str(image_path),
                        "detector": result["detector"],
                        "detections": len(result["detections"]),
                    },
                )
            )
            evidence.append(
                EvidenceItem(
                    source=str(image_path),
                    type="image_analysis",
                    content=self._evidence_text(result),
                    confidence=result["confidence"],
                    metadata={
                        "affected_ratio": result["affected_ratio"],
                        "area_km2": result["area_km2"],
                        "method": result["method"],
                        "detections": result["detections"],
                    },
                )
            )

        aggregate = self._aggregate(results)
        area_text = (
            f"，估算面积 {aggregate['area_km2']:.3f} km²"
            if aggregate.get("area_km2") is not None
            else "；未提供空间分辨率，暂不换算真实面积"
        )
        summary = (
            f"【遥感影像分析】已处理 {len(results)} 张影像；"
            f"疑似{aggregate['affected_class_name']}覆盖占比 {aggregate['affected_ratio']:.2%}{area_text}。"
        )

        return ToolResult(
            summary=f"{summary} Object detector found {aggregate['detection_count']} disaster candidate boxes.",
            evidence=evidence,
            artifacts=artifacts,
            confidence=aggregate["confidence"],
            need_user_confirm=True,
            data={
                "remote_sensing_status": "analyzed",
                "mode": mode,
                "aggregate": aggregate,
                "images": results,
            },
        )

    def _analyze_image(
        self,
        Image: Any,
        ImageDraw: Any,
        image_path: Path,
        mode: str,
        params: dict[str, Any],
        processed_dir: Path,
    ) -> dict[str, Any]:
        with Image.open(image_path) as image:
            original_width, original_height = image.size
            rgb = image.convert("RGB")

        model_result = self._analyze_with_disaster_pipeline(
            image_path,
            params,
            processed_dir,
            original_width,
            original_height,
        )
        if model_result is not None:
            return model_result

        analysis_image = rgb.copy()
        max_dimension = self._positive_int(params.get("max_dimension"), default=1024)
        analysis_image.thumbnail((max_dimension, max_dimension))

        pixels = list(analysis_image.getdata())
        affected_flags: list[bool] = []
        class_counts = {"water": 0, "burned": 0, "bare_soil": 0}

        for red, green, blue in pixels:
            water = self._is_water(red, green, blue)
            burned = self._is_burned_or_fire(red, green, blue)
            bare_soil = self._is_bare_soil(red, green, blue)
            class_counts["water"] += int(water)
            class_counts["burned"] += int(burned)
            class_counts["bare_soil"] += int(bare_soil)
            affected_flags.append(self._is_affected(mode, water, burned, bare_soil))

        total_pixels = max(len(pixels), 1)
        affected_pixels = sum(affected_flags)
        affected_ratio = affected_pixels / total_pixels
        affected_class = self._affected_class(mode, class_counts)
        affected_class_name = self._class_name(affected_class)
        area_km2 = self._estimate_area_km2(affected_ratio, original_width, original_height, params)
        confidence = self._estimate_confidence(affected_ratio, params)
        overlay_path = self._write_overlay(Image, analysis_image, affected_flags, image_path, processed_dir)
        detector = self._detector(params)
        detections = detector.detect(analysis_image, mode=mode)
        detection_path = detector.write_annotated_image(ImageDraw, analysis_image, detections, image_path, processed_dir)

        return {
            "image_path": str(image_path),
            "width": original_width,
            "height": original_height,
            "analysis_width": analysis_image.width,
            "analysis_height": analysis_image.height,
            "affected_class": affected_class,
            "affected_class_name": affected_class_name,
            "affected_pixels": affected_pixels,
            "total_pixels": total_pixels,
            "affected_ratio": affected_ratio,
            "area_km2": area_km2,
            "confidence": confidence,
            "overlay_path": str(overlay_path),
            "detection_path": str(detection_path),
            "method": "pillow_color_heuristic_v1",
            "detector": "pillow_connected_component_disaster_detector_v1",
            "model_status": "fallback",
            "model_error": params.get("_disaster_model_error"),
            "detections": detections,
            "class_ratios": {key: count / total_pixels for key, count in class_counts.items()},
        }

    def _analyze_with_disaster_pipeline(
        self,
        image_path: Path,
        params: dict[str, Any],
        processed_dir: Path,
        original_width: int,
        original_height: int,
    ) -> dict[str, Any] | None:
        if not self._use_disaster_pipeline(params):
            return None

        threshold = self._positive_float(
            params.get("disaster_gate_threshold")
            if params.get("disaster_gate_threshold") is not None
            else settings.DISASTER_GATE_THRESHOLD
        )
        detector = DisasterPipelineDetector(
            model_dir=params.get("disaster_model_dir") or settings.DISASTER_MODEL_DIR,
            device=str(params.get("disaster_model_device") or settings.DISASTER_MODEL_DEVICE or "auto"),
            gate_threshold=threshold,
        )
        try:
            result = detector.analyze(image_path, processed_dir)
        except DisasterModelUnavailable as exc:
            params["_disaster_model_error"] = str(exc)
            return None

        result["area_km2"] = self._estimate_area_km2(
            result["affected_ratio"],
            original_width,
            original_height,
            params,
        )
        return result

    def _use_disaster_pipeline(self, params: dict[str, Any]) -> bool:
        value = params.get("use_disaster_pipeline", settings.DISASTER_MODEL_ENABLED)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _write_overlay(
        self,
        Image: Any,
        image: Any,
        affected_flags: list[bool],
        source_path: Path,
        processed_dir: Path,
    ) -> Path:
        processed_dir.mkdir(parents=True, exist_ok=True)
        rgba = image.convert("RGBA")
        overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        overlay.putdata([(255, 40, 40, 120) if flag else (0, 0, 0, 0) for flag in affected_flags])
        composite = Image.alpha_composite(rgba, overlay)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = processed_dir / f"{source_path.stem}_{timestamp}_overlay.png"
        composite.save(output_path)
        return output_path

    def _collect_image_paths(self, tool_input: ToolInput) -> tuple[list[Path], list[str]]:
        raw_values: list[Any] = []
        uploaded_path_by_name: dict[str, str] = {}
        params = tool_input.params or {}
        for key in ("image_path", "image_paths", "remote_sensing_path", "remote_sensing_paths", "file_path", "file_paths"):
            if key in params:
                raw_values.append(params[key])
        for file_info in tool_input.files:
            uploaded_path = file_info.get("path") or file_info.get("file_path")
            uploaded_name = file_info.get("name") or file_info.get("filename") or Path(str(uploaded_path or "")).name
            if uploaded_path and uploaded_name:
                uploaded_path_by_name[str(uploaded_name).lower()] = str(uploaded_path)
            raw_values.append(uploaded_path)
        raw_values.extend(match.group(1) for match in IMAGE_PATH_PATTERN.finditer(tool_input.query or ""))

        paths: list[Path] = []
        invalid: list[str] = []
        for item in self._flatten(raw_values):
            if isinstance(item, dict):
                item = item.get("path") or item.get("file_path")
            if item is None or str(item).strip() == "":
                continue
            raw_item = str(item).strip()
            candidate_item = self._normalize_candidate_path(raw_item)
            uploaded_match = uploaded_path_by_name.get(Path(candidate_item).name.lower())
            path = self._resolve_existing_path(uploaded_match or candidate_item)
            if path is None:
                if uploaded_match or (paths and Path(candidate_item).name.lower() in uploaded_path_by_name):
                    continue
                invalid.append(raw_item)
                continue
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                invalid.append(raw_item)
                continue
            paths.append(path)

        return list(dict.fromkeys(paths)), list(dict.fromkeys(invalid))

    def _normalize_candidate_path(self, raw_path: str) -> str:
        value = raw_path.strip().strip('"\'`[]()<>')
        if not re.match(r"^[A-Za-z]:[\\/]", value) and ("：" in value or ":" in value):
            value = re.split(r"[:：]", value)[-1].strip()
        return value.strip().strip('"\'`[]()<>')

    def _resolve_existing_path(self, raw_path: str) -> Path | None:
        path = Path(raw_path).expanduser()
        candidates = [path]
        if not path.is_absolute():
            candidates.extend([Path.cwd() / path, Path.cwd().parent / path])
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        return None

    def _processed_dir(self, context: ToolContext | None) -> Path:
        task_id = context.task_id if context and context.task_id is not None else "unknown"
        return Path("data") / "remote_sensing" / "processed" / str(task_id)

    def _infer_mode(self, query: str, params: dict[str, Any]) -> str:
        text = f"{query} {params.get('disaster_type', '')} {params.get('mode', '')}".lower()
        if any(word in text for word in ("火", "fire", "burn", "烧毁", "燃烧")):
            return "fire"
        if any(word in text for word in ("滑坡", "landslide", "泥石流", "裸地")):
            return "landslide"
        return "flood"

    def _is_affected(self, mode: str, water: bool, burned: bool, bare_soil: bool) -> bool:
        if mode == "fire":
            return burned
        if mode == "landslide":
            return bare_soil
        return water

    def _affected_class(self, mode: str, class_counts: dict[str, int]) -> str:
        if mode == "fire":
            return "burned"
        if mode == "landslide":
            return "bare_soil"
        return "water"

    def _class_name(self, affected_class: str) -> str:
        return {
            "water": "洪涝/水体",
            "burned": "火点/烧毁区域",
            "bare_soil": "裸地/滑坡疑似区域",
        }.get(affected_class, "灾害影响区域")

    def _is_water(self, red: int, green: int, blue: int) -> bool:
        blue_water = blue > 70 and blue >= green * 0.95 and blue >= red * 1.15 and (blue - red) > 15
        dark_water = red < 65 and green < 85 and blue < 105 and blue >= red * 0.85
        cyan_water = green > 80 and blue > 90 and red < 95 and abs(green - blue) < 60
        return blue_water or dark_water or cyan_water

    def _is_burned_or_fire(self, red: int, green: int, blue: int) -> bool:
        active_fire = red > 165 and green > 55 and blue < 90 and red > green * 1.25
        burn_scar = red < 80 and green < 75 and blue < 75 and abs(red - green) < 25 and abs(green - blue) < 25
        return active_fire or burn_scar

    def _is_bare_soil(self, red: int, green: int, blue: int) -> bool:
        brown = red > 95 and green > 70 and blue < 95 and red >= green and green >= blue
        bright_soil = red > 130 and green > 105 and blue > 75 and red > blue * 1.2
        return brown or bright_soil

    def _estimate_area_km2(
        self,
        affected_ratio: float,
        original_width: int,
        original_height: int,
        params: dict[str, Any],
    ) -> float | None:
        pixel_area_m2 = self._positive_float(params.get("pixel_area_m2"))
        if pixel_area_m2 is None:
            resolution_m = params.get("resolution_m") or params.get("pixel_size_m")
            if resolution_m is not None:
                resolution_m_float = self._positive_float(resolution_m)
                if resolution_m_float is not None:
                    pixel_area_m2 = resolution_m_float**2
        if pixel_area_m2 is None:
            return None
        area_m2 = affected_ratio * original_width * original_height * pixel_area_m2
        return area_m2 / 1_000_000

    def _detector(self, params: dict[str, Any]) -> DisasterObjectDetector:
        min_area_ratio = self._positive_float(params.get("detection_min_area_ratio"))
        max_detections = self._positive_int(params.get("max_detections_per_class"), default=8)
        scope = str(params.get("detection_scope") or "all").lower()
        if scope not in {"all", "mode"}:
            scope = "all"
        return DisasterObjectDetector(
            min_area_ratio=min_area_ratio if min_area_ratio is not None else 0.0015,
            max_detections_per_class=max_detections,
            scope=scope,
        )

    def _positive_int(self, value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _positive_float(self, value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _estimate_confidence(self, affected_ratio: float, params: dict[str, Any]) -> float:
        base = 0.58
        if affected_ratio > 0.01:
            base += min(0.22, affected_ratio * 0.7)
        if params.get("resolution_m") or params.get("pixel_area_m2"):
            base += 0.06
        return round(min(base, 0.86), 2)

    def _aggregate(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        total_pixels = sum(item["total_pixels"] for item in results) or 1
        affected_pixels = sum(item["affected_pixels"] for item in results)
        detection_count = sum(len(item.get("detections", [])) for item in results)
        area_values = [item["area_km2"] for item in results if item.get("area_km2") is not None]
        confidence = sum(item["confidence"] for item in results) / len(results)
        class_counts: dict[str, int] = {}
        for item in results:
            class_counts[item["affected_class"]] = class_counts.get(item["affected_class"], 0) + item["affected_pixels"]
        affected_class = max(class_counts, key=class_counts.get) if class_counts else "unknown"

        return {
            "affected_class": affected_class,
            "affected_class_name": self._class_name(affected_class),
            "affected_pixels": affected_pixels,
            "total_pixels": total_pixels,
            "affected_ratio": affected_pixels / total_pixels,
            "area_km2": sum(area_values) if area_values else None,
            "confidence": round(confidence, 2),
            "detection_count": detection_count,
        }

    def _evidence_text(self, result: dict[str, Any]) -> str:
        area_text = f"，估算面积 {result['area_km2']:.3f} km²" if result.get("area_km2") is not None else ""
        return (
            f"影像 {Path(result['image_path']).name} 检测到疑似{result['affected_class_name']}，"
            f"覆盖占比 {result['affected_ratio']:.2%}{area_text}。"
        )

    def _flatten(self, values: list[Any]) -> list[Any]:
        flattened: list[Any] = []
        for value in values:
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                flattened.extend(self._flatten(list(value)))
            else:
                flattened.append(value)
        return flattened

    def _failed(self, summary: str, reason: str, **extra: Any) -> ToolResult:
        return ToolResult(
            summary=summary,
            confidence=0.0,
            data={"remote_sensing_status": "failed", "reason": reason, **extra},
        )
