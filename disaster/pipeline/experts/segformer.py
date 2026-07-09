import os
import numpy as np
import torch
import torch.nn.functional as F
from pathlib import Path
from PIL import Image
from safetensors.torch import load_file as load_safetensors
from transformers import (
    SegformerConfig,
    SegformerForSemanticSegmentation,
    SegformerImageProcessor,
)

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 类别定义（直接内联，不依赖 train_segformer.py）
ID2LABEL = {0: "background", 1: "pipe", 2: "construction_area"}
LABEL2ID = {v: k for k, v in ID2LABEL.items()}

CLASS_NAMES = [ID2LABEL[i] for i in range(len(ID2LABEL))]
PALETTE = {
    0: (35,  35,  35),
    1: (50,  150, 255),
    2: (44,  168, 116),
}


def _letterbox(image: Image.Image, size: int) -> tuple:
    """Pad image to square while keeping aspect ratio. Returns (padded_image, (pad_left, pad_top, new_w, new_h))."""
    orig_w, orig_h = image.size
    scale = min(size / orig_w, size / orig_h)
    new_w = max(1, int(round(orig_w * scale)))
    new_h = max(1, int(round(orig_h * scale)))
    pad_left = (size - new_w) // 2
    pad_top  = (size - new_h) // 2
    canvas = Image.new("RGB", (size, size), (0, 0, 0))
    canvas.paste(image.resize((new_w, new_h), Image.BILINEAR), (pad_left, pad_top))
    return canvas, (pad_left, pad_top, new_w, new_h)


def load(checkpoint_dir: Path, device: torch.device) -> tuple:
    processor = SegformerImageProcessor.from_pretrained(
        str(checkpoint_dir),
        do_resize=False,
        do_reduce_labels=False,
        local_files_only=True,
    )

    # 加载 state_dict 并做 key 兼容：旧版 transformers 用 linear_projections，
    # 当前版本用 linear_c，需要重映射
    checkpoint_path = checkpoint_dir / "model.safetensors"
    state_dict = load_safetensors(str(checkpoint_path))
    renamed = {}
    for key, value in state_dict.items():
        if "decode_head.linear_projections" in key:
            key = key.replace("decode_head.linear_projections", "decode_head.linear_c")
        renamed[key] = value

    config = SegformerConfig.from_pretrained(str(checkpoint_dir))
    model = SegformerForSemanticSegmentation(config)
    model.load_state_dict(renamed, strict=True)
    model.to(device)
    model.eval()
    return model, processor


@torch.no_grad()
def predict(
    model,
    processor,
    image: Image.Image,
    imgsz: int,
    device: torch.device,
) -> dict:
    orig_w, orig_h = image.size
    letterboxed, (pad_left, pad_top, new_w, new_h) = _letterbox(image.convert("RGB"), imgsz)

    pixel_values = processor(images=letterboxed, return_tensors="pt")["pixel_values"].to(device)
    logits = model(pixel_values=pixel_values).logits
    logits = F.interpolate(logits, size=(imgsz, imgsz), mode="bilinear", align_corners=False)

    pred = logits.argmax(dim=1).squeeze(0).cpu().numpy().astype(np.uint8)
    # 裁掉 padding，还原到原始分辨率
    pred = pred[pad_top:pad_top + new_h, pad_left:pad_left + new_w]
    mask = np.array(Image.fromarray(pred).resize((orig_w, orig_h), Image.NEAREST))

    total = mask.size
    counts = {CLASS_NAMES[i]: int((mask == i).sum()) for i in range(len(CLASS_NAMES))}
    ratios = {k: round(v / total, 4) for k, v in counts.items()}

    return {"mask": mask, "pixel_counts": counts, "pixel_ratios": ratios}


def colorize(mask: np.ndarray) -> Image.Image:
    color = np.zeros((*mask.shape, 3), dtype=np.uint8)
    for cls_id, rgb in PALETTE.items():
        color[mask == cls_id] = rgb
    return Image.fromarray(color)


def overlay(image: Image.Image, mask: np.ndarray, alpha: float = 0.45) -> Image.Image:
    return Image.blend(image.convert("RGB"), colorize(mask).resize(image.size, Image.NEAREST), alpha)
