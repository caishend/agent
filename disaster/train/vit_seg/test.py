#!/usr/bin/env python
"""Inference script for ViT-Small segmentation."""

import os
import sys
import argparse
import numpy as np
from PIL import Image

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import torch
import torchvision.transforms.functional as TF

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from model import ViTSeg

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

CLASS_COLORS = np.array([
    [255,   0,   0],   # 0 landslide
    [255, 255,   0],   # 1 crack
    [  0, 255, 255],   # 2 rockfall
    [255,   0, 255],   # 3 sinkhole
    [255, 165,   0],   # 4 debris_flow
    [ 30,  30,  30],   # 5 background
], dtype=np.uint8)


def load_model(checkpoint_path: str, device: torch.device,
               image_size: int) -> torch.nn.Module:
    vit_ckpt = config.VIT_CKPT if os.path.isfile(config.VIT_CKPT) else None
    model = ViTSeg(
        num_classes=config.NUM_CLASSES,
        img_size=image_size,
        checkpoint_path=vit_ckpt,  # use local pretrained weights to avoid network download
    ).to(device)

    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    epoch    = ckpt.get("epoch", "?")
    best_iou = ckpt.get("best_val_iou", "?")
    print(f"Loaded: {checkpoint_path}  (epoch={epoch}, best_val_mIoU={best_iou})")
    return model


def preprocess(image_path: str, image_size: int) -> torch.Tensor:
    img = Image.open(image_path).convert("RGB")
    img = TF.resize(img, [image_size, image_size],
                    interpolation=TF.InterpolationMode.BILINEAR)
    img = TF.to_tensor(img)
    return TF.normalize(img, mean=config.MEAN, std=config.STD)


@torch.no_grad()
def predict(model, img_tensor: torch.Tensor, device: torch.device) -> np.ndarray:
    logits = model(img_tensor.unsqueeze(0).to(device))
    return logits.argmax(dim=1).squeeze().cpu().numpy().astype(np.uint8)


def save_result(orig_image: Image.Image, pred_mask: np.ndarray,
                save_dir: str, filename: str):
    os.makedirs(save_dir, exist_ok=True)
    base = os.path.splitext(filename)[0]

    Image.fromarray(pred_mask).save(os.path.join(save_dir, f"{base}_mask.png"))

    color_map = CLASS_COLORS[pred_mask.astype(np.int32)]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    axes[0].imshow(orig_image);  axes[0].set_title("Original",  fontweight="bold"); axes[0].axis("off")
    axes[1].imshow(color_map);   axes[1].set_title("Prediction", fontweight="bold"); axes[1].axis("off")
    legend = [Patch(color=CLASS_COLORS[i]/255, label=config.CLASS_NAMES[i])
              for i in range(config.NUM_CLASSES)]
    axes[1].legend(handles=legend, loc="lower right", fontsize=7)

    axes[2].imshow(orig_image)
    alpha = np.where(pred_mask != config.NUM_CLASSES - 1, 0.5, 0.0)
    axes[2].imshow(np.dstack([color_map.astype(np.float32)/255, alpha]))
    axes[2].set_title("Overlay", fontweight="bold"); axes[2].axis("off")

    fig.suptitle(f"ViTSeg: {filename}", fontsize=14, fontweight="bold")
    plt.tight_layout()
    vis_path = os.path.join(save_dir, f"{base}_result.png")
    fig.savefig(vis_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return vis_path


def main():
    parser = argparse.ArgumentParser(description="ViT-Small segmentation inference")
    parser.add_argument("--test_dir",   type=str,
                        default=os.path.join(PROJECT_ROOT, "merged_five_clean", "test", "images"))
    parser.add_argument("--checkpoint", type=str,
                        default=os.path.join(config.CHECKPOINT_DIR, "best.pth"))
    parser.add_argument("--output_dir", type=str,
                        default=os.path.join(config.OUTPUT_DIR, "test_results"))
    parser.add_argument("--image_size", type=int,  default=config.IMAGE_SIZE)
    parser.add_argument("--device",     type=str,  default=config.DEVICE)
    args = parser.parse_args()

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    if not os.path.exists(args.test_dir):
        print(f"Error: test dir not found: {args.test_dir}"); return
    if not os.path.exists(args.checkpoint):
        print(f"Error: checkpoint not found: {args.checkpoint}"); return

    model = load_model(args.checkpoint, device, args.image_size)

    valid_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}
    image_files = sorted(f for f in os.listdir(args.test_dir)
                         if os.path.splitext(f)[1].lower() in valid_exts)
    if not image_files:
        print(f"No images in {args.test_dir}"); return

    print(f"\nFound {len(image_files)} images")
    for i, fname in enumerate(image_files):
        orig     = Image.open(os.path.join(args.test_dir, fname)).convert("RGB")
        tensor   = preprocess(os.path.join(args.test_dir, fname), args.image_size)
        pred     = predict(model, tensor, device)
        pred_full = np.array(Image.fromarray(pred).resize(orig.size, Image.NEAREST))
        vis = save_result(orig, pred_full, args.output_dir, fname)
        print(f"[{i+1}/{len(image_files)}] {fname}  →  {vis}")

    print(f"\nDone. Results: {args.output_dir}")


if __name__ == "__main__":
    main()
