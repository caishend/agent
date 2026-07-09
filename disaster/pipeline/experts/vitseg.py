import sys
from pathlib import Path

import numpy as np
import torch
import torchvision.transforms.functional as TF
from PIL import Image

# 把 disaster/vit_seg 加入路径
_VITSEG_DIR = Path(__file__).parent.parent.parent / "disaster" / "vit_seg"
sys.path.insert(0, str(_VITSEG_DIR))
sys.path.insert(0, str(_VITSEG_DIR.parent))   # disaster/ 本身（config 在这一层）

from config import config as _cfg
from model import ViTSeg

CLASS_NAMES  = ["landslide", "crack", "rockfall", "sinkhole", "debris_flow", "background"]
CLASS_COLORS = np.array([
    [255,   0,   0],   # landslide
    [255, 255,   0],   # crack
    [  0, 255, 255],   # rockfall
    [255,   0, 255],   # sinkhole
    [255, 165,   0],   # debris_flow
    [ 30,  30,  30],   # background
], dtype=np.uint8)


def load(weights_path: Path, backbone_ckpt: Path, device: torch.device) -> ViTSeg:
    backbone = str(backbone_ckpt) if backbone_ckpt.is_file() else None
    model = ViTSeg(
        num_classes=_cfg.NUM_CLASSES,
        img_size=_cfg.IMAGE_SIZE,
        checkpoint_path=backbone,
    ).to(device)
    ckpt = torch.load(weights_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return model


@torch.no_grad()
def predict(model: ViTSeg, image: Image.Image, imgsz: int, device: torch.device) -> dict:
    orig_w, orig_h = image.size

    tensor = TF.to_tensor(TF.resize(image.convert("RGB"), [imgsz, imgsz]))
    tensor = TF.normalize(tensor, mean=_cfg.MEAN, std=_cfg.STD)

    logits = model(tensor.unsqueeze(0).to(device))
    mask = logits.argmax(dim=1).squeeze().cpu().numpy().astype(np.uint8)

    # 还原到原始分辨率
    mask_full = np.array(Image.fromarray(mask).resize((orig_w, orig_h), Image.NEAREST))

    counts = {CLASS_NAMES[i]: int((mask_full == i).sum()) for i in range(len(CLASS_NAMES))}
    total  = mask_full.size
    ratios = {k: round(v / total, 4) for k, v in counts.items()}

    return {"mask": mask_full, "pixel_counts": counts, "pixel_ratios": ratios}


def colorize(mask: np.ndarray) -> Image.Image:
    return Image.fromarray(CLASS_COLORS[mask.astype(np.int32)])


def overlay(image: Image.Image, mask: np.ndarray, alpha: float = 0.5) -> Image.Image:
    color = colorize(mask).resize(image.size, Image.NEAREST)
    return Image.blend(image.convert("RGB"), color, alpha)
