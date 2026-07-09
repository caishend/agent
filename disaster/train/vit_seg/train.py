#!/usr/bin/env python
"""Training script for ViT-Small segmentation."""

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import os
import sys
import time
import argparse
import numpy as np

import torch
import torch.optim as optim
from tqdm import tqdm

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from model import ViTSeg
from data import get_dataloaders
from utils import BCEDiceLoss, MetricTracker, Visualizer


def format_metrics(metrics: dict, prefix: str = "") -> str:
    items = [f"{k}={v:.4f}" for k, v in metrics.items() if isinstance(v, float)]
    return prefix + " | ".join(items)


def train_epoch(model, loader, criterion, optimizer, device,
                tracker: MetricTracker, epoch: int):
    model.train()
    tracker.reset()

    pbar = tqdm(loader, desc=f"Train E{epoch:03d}", leave=False)
    for images, masks in pbar:
        images, masks = images.to(device), masks.to(device)
        optimizer.zero_grad()
        preds = model(images)
        loss  = criterion(preds, masks)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        tracker.update(loss.item(), preds.detach(), masks)
        cur = tracker.get_results()
        pbar.set_postfix(loss=f"{cur['loss']:.3f}", iou=f"{cur['iou']:.3f}",
                         dice=f"{cur['dice']:.3f}")

    return tracker.get_results()


@torch.no_grad()
def validate_epoch(model, loader, criterion, device,
                   tracker: MetricTracker, epoch: int):
    model.eval()
    tracker.reset()

    viz_images, viz_masks, viz_preds = [], [], []

    for batch_idx, (images, masks) in enumerate(
        tqdm(loader, desc=f"Val  E{epoch:03d}", leave=False)
    ):
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

    return tracker.get_results(), viz_images, viz_masks, viz_preds


def main():
    parser = argparse.ArgumentParser(description="ViT-Small Segmentation Training")
    parser.add_argument("--epochs",      type=int,   default=config.EPOCHS)
    parser.add_argument("--batch_size",  type=int,   default=config.BATCH_SIZE)
    parser.add_argument("--image_size",  type=int,   default=config.IMAGE_SIZE)
    parser.add_argument("--lr_backbone", type=float, default=config.LR_BACKBONE)
    parser.add_argument("--lr_head",     type=float, default=config.LR_HEAD)
    parser.add_argument("--device",      type=str,   default=config.DEVICE)
    parser.add_argument("--resume",      type=str,   default=None)
    parser.add_argument("--val_only",    action="store_true")
    args = parser.parse_args()

    config.create_dirs()
    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # ── Data ──────────────────────────────────────────────
    train_loader, val_loader, test_loader = get_dataloaders(
        data_dir=config.DATA_DIR,
        image_size=args.image_size,
        batch_size=args.batch_size,
        num_workers=config.NUM_WORKERS,
        mean=config.MEAN,
        std=config.STD,
    )
    print(f"Train: {len(train_loader.dataset)}  Val: {len(val_loader.dataset)}"
          f"  Test: {len(test_loader.dataset)}")

    # ── Model ─────────────────────────────────────────────
    ckpt_path = config.VIT_CKPT if os.path.isfile(config.VIT_CKPT) else None
    if ckpt_path:
        print(f"Loading pretrained weights from: {ckpt_path}")
    else:
        print(f"Pretrained file not found at {config.VIT_CKPT}, starting from scratch.")

    model = ViTSeg(
        num_classes=config.NUM_CLASSES,
        img_size=args.image_size,
        checkpoint_path=ckpt_path,
    ).to(device)
    n = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"ViTSeg (vit_small_patch16_224)  |  {n/1e6:.2f}M params")

    # ── Loss & Optimizer ──────────────────────────────────
    criterion = BCEDiceLoss(num_classes=config.NUM_CLASSES,
                            alpha=config.CE_WEIGHT, beta=config.DICE_WEIGHT)
    optimizer = optim.AdamW(
        model.param_groups(args.lr_backbone, args.lr_head),
        weight_decay=config.WEIGHT_DECAY,
    )
    scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=args.epochs - config.LR_WARMUP_EPOCHS,
        eta_min=config.LR_MIN,
    )

    def warmup_lambda(epoch):
        if epoch < config.LR_WARMUP_EPOCHS:
            return (epoch + 1) / config.LR_WARMUP_EPOCHS
        return 1.0

    warmup_scheduler = optim.lr_scheduler.LambdaLR(optimizer, warmup_lambda)

    # ── Resume ────────────────────────────────────────────
    start_epoch  = 0
    best_val_iou = 0.0
    no_improve   = 0
    history = {
        "train_loss": [], "val_loss": [],
        "train_iou":  [], "val_iou":  [],
        "train_dice": [], "val_dice": [],
        "train_accuracy": [], "val_accuracy": [],
    }

    if args.resume:
        ckpt = torch.load(args.resume, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state_dict"])
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        start_epoch  = ckpt["epoch"] + 1
        best_val_iou = ckpt.get("best_val_iou", 0.0)
        no_improve   = ckpt.get("no_improve", 0)
        history      = ckpt.get("history", history)
        print(f"Resumed from {args.resume}, epoch {start_epoch}")

    # ── Training ──────────────────────────────────────────
    visualizer    = Visualizer(config.OUTPUT_DIR)
    train_tracker = MetricTracker(num_classes=config.NUM_CLASSES)
    val_tracker   = MetricTracker(num_classes=config.NUM_CLASSES)

    if args.val_only:
        val_results, v_imgs, v_msks, v_preds = validate_epoch(
            model, val_loader, criterion, device, val_tracker, epoch=0
        )
        print(format_metrics(val_results, prefix="Validation: "))
        visualizer.plot_predictions(v_imgs, v_msks, v_preds, epoch=0,
                                    mean=config.MEAN, std=config.STD)
        return

    print(f"\n{'='*60}")
    print(f"ViTSeg (vit_small_patch16_224)  |  {args.epochs} epochs  |  "
          f"{args.image_size}x{args.image_size}  |  bs={args.batch_size}")
    print(f"LR backbone={args.lr_backbone:.1e}  head={args.lr_head:.1e}  device={device}")
    print(f"Early stop patience: {config.EARLY_STOP_PATIENCE}")
    print(f"{'='*60}\n")

    for epoch in range(start_epoch, args.epochs):
        t0 = time.time()

        train_results = train_epoch(
            model, train_loader, criterion, optimizer, device, train_tracker, epoch
        )

        if epoch < config.LR_WARMUP_EPOCHS:
            warmup_scheduler.step()
        else:
            scheduler.step()

        current_lr = optimizer.param_groups[0]["lr"]

        val_results, viz_imgs, viz_msks, viz_preds = validate_epoch(
            model, val_loader, criterion, device, val_tracker, epoch
        )

        for k in ["loss", "iou", "dice", "accuracy"]:
            history[f"train_{k}"].append(train_results[k])
            history[f"val_{k}"].append(val_results[k])

        elapsed = time.time() - t0
        print(f"\n--- Epoch {epoch+1}/{args.epochs} ({elapsed:.1f}s) LR={current_lr:.2e} ---")
        print(format_metrics(train_results, prefix="  Train | "))
        print(format_metrics(val_results,   prefix="  Val   | "))

        pci = val_results.get("per_class_iou", [])
        if pci:
            print("  PerClass IoU | " + " | ".join(
                f"{config.CLASS_NAMES[i]}={pci[i]:.3f}" for i in range(len(pci))
            ))

        visualizer.plot_training_curves(history)
        visualizer.plot_predictions(viz_imgs, viz_msks, viz_preds, epoch=epoch + 1,
                                    mean=config.MEAN, std=config.STD)

        is_best = val_results["iou"] > best_val_iou
        if is_best:
            best_val_iou = val_results["iou"]
            no_improve   = 0
            print(f"  [BEST] New best mIoU: {best_val_iou:.4f}")
        else:
            no_improve += 1
            print(f"  [patience {no_improve}/{config.EARLY_STOP_PATIENCE}]")

        ckpt = {
            "epoch":                epoch,
            "model_state_dict":     model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "best_val_iou":         best_val_iou,
            "no_improve":           no_improve,
            "history":              history,
        }
        torch.save(ckpt, os.path.join(config.CHECKPOINT_DIR, "last.pth"))
        if is_best:
            torch.save(ckpt, os.path.join(config.CHECKPOINT_DIR, "best.pth"))

        if no_improve >= config.EARLY_STOP_PATIENCE:
            print(f"\n[Early Stop] No improvement for {no_improve} epochs. Stopping.")
            break

    # ── Test ──────────────────────────────────────────────
    print(f"\n{'='*60}\nEvaluating on test set with best model...\n{'='*60}")

    best_ckpt = torch.load(os.path.join(config.CHECKPOINT_DIR, "best.pth"),
                           map_location=device, weights_only=False)
    model.load_state_dict(best_ckpt["model_state_dict"])
    print(f"Loaded best model (epoch {best_ckpt['epoch']+1}, val mIoU={best_val_iou:.4f})")

    test_tracker = MetricTracker(num_classes=config.NUM_CLASSES)
    test_results, tst_imgs, tst_msks, tst_preds = validate_epoch(
        model, test_loader, criterion, device, test_tracker, epoch=args.epochs
    )
    print(format_metrics(test_results, prefix="  Test  | "))

    pci = test_results.get("per_class_iou", [])
    if pci:
        print("  PerClass IoU | " + " | ".join(
            f"{config.CLASS_NAMES[i]}={pci[i]:.3f}" for i in range(len(pci))
        ))

    visualizer.plot_confusion_matrix(conf_matrix=test_tracker.conf_matrix,
                                     class_names=config.CLASS_NAMES)
    visualizer.plot_predictions(tst_imgs, tst_msks, tst_preds, epoch=args.epochs + 1,
                                mean=config.MEAN, std=config.STD,
                                save_path=os.path.join(config.OUTPUT_DIR, "test_predictions.png"))
    visualizer.plot_training_curves(history)

    print(f"\nDone!  Best Val mIoU: {best_val_iou:.4f}")
    print(f"Outputs: {config.OUTPUT_DIR}")


if __name__ == "__main__":
    main()
