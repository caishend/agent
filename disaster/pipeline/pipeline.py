"""
DisasterPipeline: 门控 + 三专家的完整推理流程

用法（作为模块）:
    from pipeline.pipeline import DisasterPipeline
    pipe = DisasterPipeline()
    result = pipe.run("path/to/image.jpg")
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import torch
from PIL import Image

from pipeline import config
from pipeline.experts import gate, snow, vitseg, segformer


class DisasterPipeline:
    def __init__(
        self,
        device: Optional[str] = None,
        gate_threshold: Optional[float] = None,
    ):
        dev = device or config.DEVICE
        if dev == "auto":
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(dev)

        self.gate_threshold = gate_threshold if gate_threshold is not None else config.GATE_THRESHOLD

        print(f"[Pipeline] device={self.device}  gate_threshold={self.gate_threshold}")
        self._load_models()

    # ── 模型加载 ─────────────────────────────────────────────────────────────

    def _load_models(self):
        print("[Pipeline] loading GateModel ...")
        self.gate_model, ckpt_threshold = gate.load(config.WEIGHTS["gate"], self.device)
        # checkpoint 里存了训练时最优阈值，如果用户没有手动覆盖则采用它
        if config.GATE_THRESHOLD == 0.5:
            self.gate_threshold = ckpt_threshold

        print("[Pipeline] loading YOLO (snow/water/flood) ...")
        self.snow_model = snow.load(config.WEIGHTS["snow"], self.device)

        print("[Pipeline] loading ViTSeg (landslide/crack/...) ...")
        self.vitseg_model = vitseg.load(
            config.WEIGHTS["vitseg"],
            config.VITSEG_BACKBONE_CKPT,
            self.device,
        )

        print("[Pipeline] loading SegFormer (pipe/construction) ...")
        self.segformer_model, self.segformer_processor = segformer.load(
            config.WEIGHTS["segformer"], self.device
        )
        print("[Pipeline] all models loaded.")

    # ── 单张推理 ─────────────────────────────────────────────────────────────

    def run(self, image_path: str | Path) -> dict:
        """
        对单张图片执行完整 pipeline。

        Returns:
            {
              "image_path": str,
              "gate": { probabilities, decisions, threshold },
              "snow":      { detections }           | None,
              "vitseg":    { mask, pixel_counts, pixel_ratios } | None,
              "segformer": { mask, pixel_counts, pixel_ratios } | None,
            }
        """
        image_path = Path(image_path)
        image = Image.open(image_path).convert("RGB")

        # 1. 门控路由
        gate_result = gate.predict(self.gate_model, image, self.gate_threshold, self.device)
        decisions   = gate_result["decisions"]

        # 2. 按路由决策调用专家
        snow_result      = None
        vitseg_result    = None
        segformer_result = None

        if decisions["group1_od"]:
            snow_result = snow.predict(
                self.snow_model, image,
                conf=config.SNOW_CONF,
                iou=config.SNOW_IOU,
                imgsz=config.SNOW_IMGSZ,
                device=self.device,
            )

        if decisions["group2_seg1"]:
            vitseg_result = vitseg.predict(
                self.vitseg_model, image,
                imgsz=config.VITSEG_IMGSZ,
                device=self.device,
            )

        if decisions["group3_seg2"]:
            segformer_result = segformer.predict(
                self.segformer_model, self.segformer_processor, image,
                imgsz=config.SEGFORMER_IMGSZ,
                device=self.device,
            )

        return {
            "image_path": str(image_path),
            "gate":       gate_result,
            "snow":       snow_result,
            "vitseg":     vitseg_result,
            "segformer":  segformer_result,
        }

    # ── 可视化 ────────────────────────────────────────────────────────────────

    def visualize(self, image_path: str | Path, result: dict, output_dir: Path) -> list[Path]:
        """
        把各专家的可视化图保存到 output_dir，返回保存的文件路径列表。
        只有被路由到的专家才会生成图片。
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        image = Image.open(image_path).convert("RGB")
        stem  = Path(image_path).stem
        saved = []

        if result["snow"] is not None:
            vis = snow.draw(image, result["snow"])
            p = output_dir / f"{stem}_snow.jpg"
            vis.save(p)
            saved.append(p)

        if result["vitseg"] is not None:
            mask = result["vitseg"]["mask"]
            panels = _make_panels(image, vitseg.colorize(mask), vitseg.overlay(image, mask))
            p = output_dir / f"{stem}_vitseg.jpg"
            panels.save(p)
            saved.append(p)

        if result["segformer"] is not None:
            mask = result["segformer"]["mask"]
            panels = _make_panels(image, segformer.colorize(mask), segformer.overlay(image, mask))
            p = output_dir / f"{stem}_segformer.jpg"
            panels.save(p)
            saved.append(p)

        return saved


# ── 辅助：三栏拼图 ────────────────────────────────────────────────────────────

def _make_panels(orig: Image.Image, color: Image.Image, blend: Image.Image) -> Image.Image:
    w, h = orig.size
    color  = color.resize((w, h), Image.NEAREST)
    blend  = blend.resize((w, h), Image.NEAREST)
    canvas = Image.new("RGB", (w * 3, h))
    canvas.paste(orig,  (0,     0))
    canvas.paste(color, (w,     0))
    canvas.paste(blend, (w * 2, 0))
    return canvas
