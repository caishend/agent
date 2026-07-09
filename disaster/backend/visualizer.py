"""
统一可视化模块
支持检测框 + 分割掩码，支持中文类别名称。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ── 类别颜色表 ────────────────────────────────────────────────────────────────
# BGR 格式（OpenCV）
_PALETTE_BGR: dict[str, tuple[int, int, int]] = {
    # snow group
    "snow":              (255, 220, 100),
    "water_accumulation":(255, 140,   0),
    "flood":             (255,  60,  60),
    # vitseg group
    "landslide":         ( 80, 180, 255),
    "crack":             ( 50, 255, 255),
    "rockfall":          (180,  50, 255),
    "sinkhole":          ( 50, 200, 100),
    "debris_flow":       (100, 100, 255),
    "background":        ( 40,  40,  40),
    # segformer group
    "pipe":              (255, 150,  50),
    "construction_area": (100, 255, 100),
}
_DEFAULT_BGR = (200, 200, 200)

# ── 中文字体（用 PIL 绘制文字再合并回 OpenCV）────────────────────────────────
_FONT_PATH = Path(__file__).parent / "assets" / "simhei.ttf"
_PIL_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _get_font(size: int = 20) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if size not in _PIL_FONT_CACHE:
        try:
            _PIL_FONT_CACHE[size] = ImageFont.truetype(str(_FONT_PATH), size)
        except Exception:
            # 回退到系统中文字体
            for fallback in [
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/simsun.ttc",
            ]:
                try:
                    _PIL_FONT_CACHE[size] = ImageFont.truetype(fallback, size)
                    break
                except Exception:
                    continue
            else:
                _PIL_FONT_CACHE[size] = ImageFont.load_default()
    return _PIL_FONT_CACHE[size]


def _color(class_name: str) -> tuple[int, int, int]:
    return _PALETTE_BGR.get(class_name, _DEFAULT_BGR)


def _put_text_cn(img_bgr: np.ndarray, text: str, xy: tuple[int, int],
                 color_bgr: tuple[int, int, int], font_size: int = 18) -> np.ndarray:
    """用 PIL 在 BGR 图上写中文，再转回 BGR ndarray。"""
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(pil)
    font = _get_font(font_size)
    r, g, b = color_bgr[2], color_bgr[1], color_bgr[0]
    # 黑色描边，增加可读性
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        draw.text((xy[0] + dx, xy[1] + dy), text, font=font, fill=(0, 0, 0))
    draw.text(xy, text, font=font, fill=(r, g, b))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


# ── 检测框绘制 ────────────────────────────────────────────────────────────────

def draw_detections(img_bgr: np.ndarray, detections: list[dict]) -> np.ndarray:
    """
    detections: list of {class_name, confidence, box_xyxy}
    """
    for det in detections:
        name  = det.get("class_name", "unknown")
        conf  = det.get("confidence", 0.0)
        box   = det.get("box_xyxy", [])
        if len(box) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in box]
        color = _color(name)

        cv2.rectangle(img_bgr, (x1, y1), (x2, y2), color, 2)

        label = f"{name} {conf:.2f}"
        text_y = max(y1 - 6, 18)
        img_bgr = _put_text_cn(img_bgr, label, (x1, text_y - 18), color, font_size=18)

    return img_bgr


# ── 分割掩码绘制 ──────────────────────────────────────────────────────────────

def draw_segmentation(
    img_bgr: np.ndarray,
    mask: np.ndarray,
    class_names: list[str],
    alpha: float = 0.45,
    show_contour: bool = True,
) -> np.ndarray:
    """
    mask: H×W uint8，像素值为类别 id
    class_names: id → name 的列表
    """
    h, w = img_bgr.shape[:2]
    overlay = img_bgr.copy()
    label_positions: list[tuple[str, tuple[int, int], tuple[int, int, int]]] = []

    for cls_id, name in enumerate(class_names):
        if name == "background":
            continue
        binary = (mask == cls_id).astype(np.uint8)
        if binary.sum() == 0:
            continue

        color = _color(name)

        # 半透明填充
        colored = np.zeros_like(img_bgr)
        colored[binary == 1] = color
        overlay = cv2.addWeighted(overlay, 1.0, colored, alpha, 0)

        # 轮廓
        if show_contour:
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(overlay, contours, -1, color, 2)

        # 记录标签位置（质心）
        ys, xs = np.where(binary == 1)
        cx, cy = int(xs.mean()), int(ys.mean())
        label_positions.append((name, (cx, cy), color))

    # 标签后绘，避免被掩码覆盖
    for name, (cx, cy), color in label_positions:
        overlay = _put_text_cn(overlay, name, (cx, cy), color, font_size=20)

    return overlay


# ── 合并绘制（检测 + 分割同时存在时）────────────────────────────────────────

def draw_all(
    image: Image.Image,
    snow_result:      Optional[dict],
    vitseg_result:    Optional[dict],
    segformer_result: Optional[dict],
    vitseg_classes:   list[str],
    segformer_classes: list[str],
) -> np.ndarray:
    """
    把所有专家结果绘制到同一张图上，返回 BGR ndarray。
    """
    img_bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)

    if vitseg_result is not None:
        img_bgr = draw_segmentation(img_bgr, vitseg_result["mask"], vitseg_classes)

    if segformer_result is not None:
        img_bgr = draw_segmentation(img_bgr, segformer_result["mask"], segformer_classes)

    if snow_result is not None:
        img_bgr = draw_detections(img_bgr, snow_result["detections"])

    return img_bgr
