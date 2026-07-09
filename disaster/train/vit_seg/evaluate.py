#!/usr/bin/env python
"""Evaluate ViT-Small segmentation model on the test split.

Usage:
    python vit_seg/evaluate.py
    python vit_seg/evaluate.py --checkpoint vit_seg/outputs/checkpoints/best.pth
    python vit_seg/evaluate.py --checkpoint vit_seg/outputs/checkpoints/last.pth --device cpu
"""

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import os
import sys
import argparse
import numpy as np

import torch
from tqdm import tqdm

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from model import ViTSeg
from data import get_dataloaders
from utils import BCEDiceLoss, MetricTracker, Visualizer


@torch.no_grad()
def evaluate(model, loader, criterion, device, num_classes):
    model.eval()
    tracker = MetricTracker(num_classes=num_classes)

    viz_images, viz_masks, viz_preds = [], [], []

    for batch_idx, (images, masks) in enumerate(tqdm(loader, desc="Test")):
        images, masks = images.to(device), masks.to(device)
        preds = model(images)
        loss  = criterion(preds, masks)
        tracker.update(loss.item(), preds, masks)

        if batch_idx == 0:
            viz_images.append(images.cpu().numpy())
            viz_masks.append(masks.cpu().numpy())
            viz_preds.append(preds.cpu().numpy())

    viz_images = np.concatenate(viz_images, axis=0)
    viz_masks  = np.concatenate(viz_masks,  axis=0)
    viz_preds  = np.concatenate(viz_preds,  axis=0)

    return tracker.get_results(), tracker.conf_matrix, viz_images, viz_masks, viz_preds


def print_results(results, class_names):
    print(f"\n{'='*60}")
    print(f"  mIoU     : {results['iou']:.4f}")
    print(f"  Dice     : {results['dice']:.4f}")
    print(f"  Pixel Acc: {results['accuracy']:.4f}")
    print(f"  Loss     : {results['loss']:.4f}")
    print(f"{'='*60}")
    print("  Per-class IoU:")
    pci = results.get("per_class_iou", [])
    for i, iou in enumerate(pci):
        name = class_names[i] if i < len(class_names) else str(i)
        print(f"    {name:<16}: {iou:.4f}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="ViT-Small segmentation test evaluation")
    parser.add_argument("--checkpoint",  type=str, default=os.path.join(config.CHECKPOINT_DIR, "best.pth"))
    parser.add_argument("--data_dir",    type=str, default=config.DATA_DIR)
    parser.add_argument("--output_dir",  type=str, default=os.path.join(config.OUTPUT_DIR, "eval"))
    parser.add_argument("--image_size",  type=int, default=config.IMAGE_SIZE)
    parser.add_argument("--batch_size",  type=int, default=config.BATCH_SIZE)
    parser.add_argument("--num_workers", type=int, default=config.NUM_WORKERS)
    parser.add_argument("--device",      type=str, default=config.DEVICE)
    args = parser.parse_args()

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    if not os.path.isfile(args.checkpoint):
        print(f"Checkpoint not found: {args.checkpoint}")
        sys.exit(1)

    # ── Data ──────────────────────────────────────────────
    _, _, test_loader = get_dataloaders(
        data_dir=args.data_dir,
        image_size=args.image_size,
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        mean=config.MEAN,
        std=config.STD,
    )
    print(f"Test samples: {len(test_loader.dataset)}")

    # ── Model ─────────────────────────────────────────────
    vit_ckpt = config.VIT_CKPT if os.path.isfile(config.VIT_CKPT) else None
    model = ViTSeg(
        num_classes=config.NUM_CLASSES,
        img_size=args.image_size,
        checkpoint_path=vit_ckpt,
    ).to(device)

    ckpt = torch.load(args.checkpoint, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    epoch    = ckpt.get("epoch", "?")
    best_iou = ckpt.get("best_val_iou", "?")
    print(f"Loaded: {args.checkpoint}  (epoch={epoch}, best_val_mIoU={best_iou})")

    # ── Evaluate ──────────────────────────────────────────
    criterion = BCEDiceLoss(
        num_classes=config.NUM_CLASSES,
        alpha=config.CE_WEIGHT,
        beta=config.DICE_WEIGHT,
    )

    results, conf_matrix, viz_imgs, viz_msks, viz_preds = evaluate(
        model, test_loader, criterion, device, config.NUM_CLASSES
    )

    print_results(results, config.CLASS_NAMES)

    # ── Save outputs ──────────────────────────────────────
    os.makedirs(args.output_dir, exist_ok=True)
    visualizer = Visualizer(args.output_dir)

    visualizer.plot_confusion_matrix(
        conf_matrix=conf_matrix,
        class_names=config.CLASS_NAMES,
    )
    visualizer.plot_predictions(
        viz_imgs, viz_msks, viz_preds,
        epoch=0,
        mean=config.MEAN, std=config.STD,
        save_path=os.path.join(args.output_dir, "test_predictions.png"),
    )

    print(f"Outputs saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
