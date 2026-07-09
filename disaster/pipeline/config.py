"""
Pipeline 全局配置
所有权重路径、推理参数都在这里改，其他文件不需要动。
"""

from pathlib import Path

# 项目根目录（config.py 的上一级）
ROOT = Path(__file__).parent.parent

# ── 权重路径 ──────────────────────────────────────────────────────────────────

WEIGHTS = {
    # GateModel: ResNet-50 多标签分类器
    "gate": ROOT / "saved_models" / "gate" / "gating_model_final.pth",

    # YOLO11m: 目标检测 (snow / water_accumulation / flood)
    "snow": ROOT / "saved_models" / "snow" / "best.pt",

    # ViT-Small: 语义分割 (landslide / crack / rockfall / sinkhole / debris_flow)
    "vitseg": ROOT / "saved_models" / "disaster" / "best.pth",

    # SegFormer MIT-B3: 语义分割 (pipe / construction_area)
    # HuggingFace 格式目录，包含 config.json / model.safetensors / preprocessor_config.json
    "segformer": ROOT / "saved_models" / "pipe_construction",
}

# ViT-Small backbone 预训练权重（timm 格式，避免联网下载）
VITSEG_BACKBONE_CKPT = ROOT / "saved_models" / "disaster" / "vit_small_patch16_224.pth"

# ── 推理参数 ──────────────────────────────────────────────────────────────────

GATE_THRESHOLD = 0.5       # GateModel sigmoid 阈值，超过则分发到对应专家

SNOW_CONF      = 0.25      # YOLO 置信度阈值
SNOW_IOU       = 0.70      # YOLO NMS IoU 阈值
SNOW_IMGSZ     = 768       # YOLO 推理分辨率

VITSEG_IMGSZ   = 512       # ViTSeg 输入分辨率

SEGFORMER_IMGSZ = 768      # SegFormer letterbox 分辨率（与训练时一致）

# ── 硬件 ──────────────────────────────────────────────────────────────────────

DEVICE = "auto"            # "auto" | "cuda" | "cpu"

# ── 输出 ──────────────────────────────────────────────────────────────────────

# 是否保存可视化结果图（各专家预测图）
SAVE_VIS = True

# 默认输出目录（run.py --output-dir 的默认值）
DEFAULT_OUTPUT_DIR = ROOT / "pipeline_output"
