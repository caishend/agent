#!/usr/bin/env python
"""Quick evaluation: run on test set with CPU, generate metrics + confusion matrix."""

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import os, sys, time, argparse
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

    for batch_idx, (images, masks) in enumerate(
        tqdm(loader, desc="Evaluating")
    ):
        images, masks = images.to(device), masks.to(device)
        preds = model(images)
        loss = criterion(preds, masks)
        tracker.update(loss.item(), preds, masks)

        if batch_idx == 0:
            viz_images.append(images.cpu().numpy())
            viz_masks.append(masks.cpu().numpy())
            viz_preds.append(preds.cpu().numpy())

    viz_images = np.concatenate(viz_images, axis=0)
    viz_masks = np.concatenate(viz_masks, axis=0)
    viz_preds = np.concatenate(viz_preds, axis=0)
    return tracker.get_results(), tracker.conf_matrix, viz_images, viz_masks, viz_preds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=str,
                        default=os.path.join(config.CHECKPOINT_DIR, "best.pth"))
    parser.add_argument("--output_dir", type=str,
                        default=os.path.join(config.OUTPUT_DIR, "eval"))
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--max_batches", type=int, default=0,
                        help="0 = all, N = only N batches")
    args = parser.parse_args()

    device = torch.device(args.device)
    print(f"Device: {device}")

    if not os.path.isfile(args.checkpoint):
        print(f"ERROR: checkpoint not found: {args.checkpoint}")
        sys.exit(1)

    # Data
    _, _, test_loader = get_dataloaders(
        data_dir=config.DATA_DIR,
        image_size=config.IMAGE_SIZE,
        batch_size=config.BATCH_SIZE,
        num_workers=config.NUM_WORKERS,
        mean=config.MEAN, std=config.STD,
    )
    n_total = len(test_loader.dataset)
    n_batches = len(test_loader)
    print(f"Test samples: {n_total}  |  Batches: {n_batches}  |  "
          f"Image size: {config.IMAGE_SIZE}")

    # Model
    vit_ckpt = config.VIT_CKPT if os.path.isfile(config.VIT_CKPT) else None
    model = ViTSeg(
        num_classes=config.NUM_CLASSES,
        img_size=config.IMAGE_SIZE,
        checkpoint_path=vit_ckpt,
    ).to(device)

    ckpt = torch.load(args.checkpoint, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    epoch = ckpt.get("epoch", "?")
    best_iou = ckpt.get("best_val_iou", "?")
    print(f"Loaded: epoch={epoch}, best_val_mIoU={best_iou}")

    # If max_batches specified, create a limited loader
    if args.max_batches > 0:
        # Create a subset
        from torch.utils.data import Subset
        n_samples = min(args.max_batches * config.BATCH_SIZE, n_total)
        indices = list(range(n_samples))
        subset = Subset(test_loader.dataset, indices)
        from torch.utils.data import DataLoader
        test_loader = DataLoader(subset, batch_size=config.BATCH_SIZE,
                                 shuffle=False, num_workers=0, pin_memory=False)
        n_batches = len(test_loader)
        print(f"Limited to {n_samples} samples ({n_batches} batches)")

    # Loss
    criterion = BCEDiceLoss(
        num_classes=config.NUM_CLASSES,
        alpha=config.CE_WEIGHT, beta=config.DICE_WEIGHT,
    )

    # Evaluate
    t0 = time.time()
    results, conf_matrix, viz_imgs, viz_msks, viz_preds = evaluate(
        model, test_loader, criterion, device, config.NUM_CLASSES
    )
    elapsed = time.time() - t0

    # Print results
    print(f"\n{'='*60}")
    print(f"  Elapsed  : {elapsed:.1f}s  ({elapsed/n_batches:.1f}s/batch)")
    print(f"  mIoU     : {results['iou']:.4f}")
    print(f"  Dice     : {results['dice']:.4f}")
    print(f"  Pixel Acc: {results['accuracy']:.4f}")
    print(f"  Loss     : {results['loss']:.4f}")
    print(f"{'='*60}")
    print("  Per-class IoU:")
    pci = results.get("per_class_iou", [])
    for i, iou in enumerate(pci):
        name = config.CLASS_NAMES[i] if i < len(config.CLASS_NAMES) else str(i)
        print(f"    {name:<16}: {iou:.4f}")
    print(f"{'='*60}\n")

    # Save
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
