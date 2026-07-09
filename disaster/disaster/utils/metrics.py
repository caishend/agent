"""Metrics for multi-class semantic segmentation evaluation."""

import torch
import numpy as np


def compute_all_metrics(pred: torch.Tensor, target: torch.Tensor,
                        num_classes: int = 6):
    """Compute multi-class segmentation metrics.

    Args:
        pred:        (B, C, H, W) logits
        target:      (B, H, W) long class indices
        num_classes: number of classes

    Returns:
        dict with keys: iou (mIoU), dice (mean Dice), accuracy (pixel acc),
                        per_class_iou, per_class_dice
    """
    pred_labels = pred.argmax(dim=1)   # (B, H, W)
    pred_flat = pred_labels.view(-1)
    target_flat = target.view(-1)

    ious, dices = [], []
    for c in range(num_classes):
        tp = ((pred_flat == c) & (target_flat == c)).sum().float()
        fp = ((pred_flat == c) & (target_flat != c)).sum().float()
        fn = ((pred_flat != c) & (target_flat == c)).sum().float()

        iou = (tp + 1e-7) / (tp + fp + fn + 1e-7)
        dice = (2 * tp + 1e-7) / (2 * tp + fp + fn + 1e-7)
        ious.append(iou.item())
        dices.append(dice.item())

    accuracy = (pred_flat == target_flat).float().mean().item()

    return {
        "iou": float(np.mean(ious)),
        "dice": float(np.mean(dices)),
        "accuracy": accuracy,
        "per_class_iou": ious,
        "per_class_dice": dices,
    }


class MetricTracker:
    """Accumulate confusion matrix over an epoch for multi-class metrics."""

    def __init__(self, num_classes: int = 6):
        self.num_classes = num_classes
        self.reset()

    def reset(self):
        self.conf_matrix = np.zeros((self.num_classes, self.num_classes), dtype=np.int64)
        self.total_loss = 0.0
        self.num_batches = 0
        # Legacy binary fields kept for visualizer compatibility
        self.tp = self.fp = self.fn = self.tn = 0

    def update(self, loss: float, pred: torch.Tensor, target: torch.Tensor,
               threshold: float = 0.5):
        self.total_loss += loss
        self.num_batches += 1

        pred_labels = pred.argmax(dim=1).cpu().numpy().reshape(-1)
        target_np = target.cpu().numpy().reshape(-1)

        for t, p in zip(target_np, pred_labels):
            self.conf_matrix[t, p] += 1

        # Update legacy binary fields (foreground = any non-background class)
        bg = self.num_classes - 1
        tp = int(((pred_labels != bg) & (target_np != bg)).sum())
        fp = int(((pred_labels != bg) & (target_np == bg)).sum())
        fn = int(((pred_labels == bg) & (target_np != bg)).sum())
        tn = int(((pred_labels == bg) & (target_np == bg)).sum())
        self.tp += tp; self.fp += fp; self.fn += fn; self.tn += tn

    def get_results(self) -> dict:
        cm = self.conf_matrix.astype(np.float64)
        eps = 1e-7
        ious, dices = [], []
        for c in range(self.num_classes):
            tp = cm[c, c]
            fp = cm[:, c].sum() - tp
            fn = cm[c, :].sum() - tp
            ious.append((tp + eps) / (tp + fp + fn + eps))
            dices.append((2 * tp + eps) / (2 * tp + fp + fn + eps))

        accuracy = cm.diagonal().sum() / (cm.sum() + eps)

        return {
            "loss": self.total_loss / max(1, self.num_batches),
            "iou": float(np.mean(ious)),
            "dice": float(np.mean(dices)),
            "accuracy": float(accuracy),
            "precision": float(np.mean(ious)),   # placeholder for display compat
            "recall": float(np.mean(dices)),      # placeholder for display compat
            "per_class_iou": ious,
        }
