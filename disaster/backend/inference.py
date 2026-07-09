"""
Pipeline 适配层
把 DisasterPipeline 的原始输出转换为统一的后端格式。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

# 确保项目根在 sys.path
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.pipeline import DisasterPipeline
from pipeline.experts.vitseg    import CLASS_NAMES as VITSEG_CLASSES
from pipeline.experts.segformer import CLASS_NAMES as SEGFORMER_CLASSES
from backend.schemas import Detection, GateInfo, Segmentation
from backend.postprocess import postprocess_outputs
from backend import visualizer

# 单例，FastAPI 启动时初始化一次
_pipeline: DisasterPipeline | None = None


def get_pipeline() -> DisasterPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = DisasterPipeline()
    return _pipeline


# ── 原始结果 → 标准结构 ───────────────────────────────────────────────────────

def _parse_gate(gate_raw: dict) -> GateInfo:
    return GateInfo(
        probabilities=gate_raw["probabilities"],
        decisions=gate_raw["decisions"],
        threshold=gate_raw["threshold"],
    )


def _parse_detections(snow_raw: dict | None) -> list[Detection]:
    if snow_raw is None:
        return []
    return [
        Detection(
            class_id=d["class_id"],
            class_name=d["class_name"],
            confidence=d["confidence"],
            box_xyxy=d["box_xyxy"],
        )
        for d in snow_raw.get("detections", [])
    ]


def _parse_segmentations(
    vitseg_raw: dict | None,
    segformer_raw: dict | None,
) -> list[Segmentation]:
    items: list[Segmentation] = []

    for raw, names in [
        (vitseg_raw,    VITSEG_CLASSES),
        (segformer_raw, SEGFORMER_CLASSES),
    ]:
        if raw is None:
            continue
        counts = raw.get("pixel_counts", {})
        ratios = raw.get("pixel_ratios", {})
        for name in names:
            if name == "background":
                continue
            if counts.get(name, 0) == 0:
                continue
            items.append(Segmentation(
                class_name=name,
                pixel_count=counts.get(name, 0),
                pixel_ratio=ratios.get(name, 0.0),
            ))

    return items


# ── 单帧推理（图片 / 视频帧通用）────────────────────────────────────────────

def run_on_image(image: Image.Image, threshold: float | None = None) -> tuple[np.ndarray, dict]:
    """
    对一张 PIL Image 执行完整推理，返回:
        annotated_bgr: np.ndarray  已绘制标注的 BGR 图像
        structured:    dict        包含 gate / detections / segmentations
    """
    pipe = get_pipeline()

    # pipeline.run 需要文件路径，这里临时用内存版本
    gate_result      = _run_gate(pipe, image, threshold)
    decisions        = gate_result["decisions"]

    from pipeline import config
    from pipeline.experts import snow as snow_expert
    from pipeline.experts import vitseg as vitseg_expert
    from pipeline.experts import segformer as segformer_expert

    snow_raw      = None
    vitseg_raw    = None
    segformer_raw = None

    if decisions["group1_od"]:
        snow_raw = snow_expert.predict(
            pipe.snow_model, image,
            conf=config.SNOW_CONF,
            iou=config.SNOW_IOU,
            imgsz=config.SNOW_IMGSZ,
            device=pipe.device,
        )

    if decisions["group2_seg1"]:
        vitseg_raw = vitseg_expert.predict(
            pipe.vitseg_model, image,
            imgsz=config.VITSEG_IMGSZ,
            device=pipe.device,
        )

    if decisions["group3_seg2"]:
        segformer_raw = segformer_expert.predict(
            pipe.segformer_model, pipe.segformer_processor, image,
            imgsz=config.SEGFORMER_IMGSZ,
            device=pipe.device,
        )

    snow_raw, vitseg_raw, segformer_raw = postprocess_outputs(
        image.size,
        snow_raw,
        vitseg_raw,
        segformer_raw,
        VITSEG_CLASSES,
        SEGFORMER_CLASSES,
    )

    annotated = visualizer.draw_all(
        image,
        snow_raw,
        vitseg_raw,
        segformer_raw,
        VITSEG_CLASSES,
        SEGFORMER_CLASSES,
    )

    structured = {
        "gate":          gate_result,
        "detections":    _parse_detections(snow_raw),
        "segmentations": _parse_segmentations(vitseg_raw, segformer_raw),
    }

    return annotated, structured


def _run_gate(pipe: DisasterPipeline, image: Image.Image, threshold: float | None = None) -> dict:
    from pipeline.experts import gate as gate_expert
    th = threshold if threshold is not None else pipe.gate_threshold
    return gate_expert.predict(pipe.gate_model, image, th, pipe.device)
