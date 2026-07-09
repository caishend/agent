"""Visualization utilities: training curves, prediction masks, confusion matrices."""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec


class Visualizer:
    """Handles all plotting for training progress and predictions."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ── Training curves ───────────────────────────────────

    def plot_training_curves(self, history: dict, save_path: str = None):
        """Plot loss and metrics over epochs.

        Args:
            history: dict with keys like 'train_loss', 'val_loss', 'train_iou',
                     'val_iou', 'train_dice', 'val_dice', 'train_accuracy', 'val_accuracy'
            save_path: path to save figure
        """
        epochs = range(1, len(history.get("train_loss", [])) + 1)
        if len(epochs) == 0:
            return

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle("ViT-UNet Training Curves", fontsize=16, fontweight="bold")

        # Loss
        ax = axes[0, 0]
        ax.plot(epochs, history["train_loss"], "b-", label="Train Loss", linewidth=2)
        if "val_loss" in history:
            ax.plot(epochs, history["val_loss"], "r-", label="Val Loss", linewidth=2)
        ax.set_xlabel("Epoch")
        ax.set_ylabel("Loss")
        ax.set_title("Loss")
        ax.legend()
        ax.grid(True, alpha=0.3)

        # IoU
        ax = axes[0, 1]
        ax.plot(epochs, history["train_iou"], "b-", label="Train IoU", linewidth=2)
        if "val_iou" in history:
            ax.plot(epochs, history["val_iou"], "r-", label="Val IoU", linewidth=2)
        ax.set_xlabel("Epoch")
        ax.set_ylabel("IoU")
        ax.set_title("IoU (Jaccard)")
        ax.legend()
        ax.grid(True, alpha=0.3)

        # Dice
        ax = axes[1, 0]
        ax.plot(epochs, history["train_dice"], "b-", label="Train Dice", linewidth=2)
        if "val_dice" in history:
            ax.plot(epochs, history["val_dice"], "r-", label="Val Dice", linewidth=2)
        ax.set_xlabel("Epoch")
        ax.set_ylabel("Dice")
        ax.set_title("Dice Coefficient")
        ax.legend()
        ax.grid(True, alpha=0.3)

        # Accuracy
        ax = axes[1, 1]
        ax.plot(epochs, history["train_accuracy"], "b-", label="Train Acc", linewidth=2)
        if "val_accuracy" in history:
            ax.plot(epochs, history["val_accuracy"], "r-", label="Val Acc", linewidth=2)
        ax.set_xlabel("Epoch")
        ax.set_ylabel("Accuracy")
        ax.set_title("Pixel Accuracy")
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        if save_path is None:
            save_path = os.path.join(self.output_dir, "training_curves.png")
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[Visualizer] Training curves saved to {save_path}")

    # ── Prediction samples ────────────────────────────────

    def plot_predictions(self, images: np.ndarray, masks: np.ndarray,
                         preds: np.ndarray, epoch: int = None,
                         save_path: str = None, mean=None, std=None):
        """Plot image, ground truth, and prediction side by side.

        Args:
            images: (N, 3, H, W) normalized tensors
            masks:  (N, H, W) int class indices 0-5
            preds:  (N, H, W) int class indices 0-5  (or (N, C, H, W) logits)
            epoch: current epoch number (for title)
            save_path: path to save
            mean, std: normalization stats for denormalization
        """
        CLASS_COLORS = np.array([
            [255,   0,   0],   # 0 landslide  red
            [255, 255,   0],   # 1 crack       yellow
            [  0, 255, 255],   # 2 rockfall    cyan
            [255,   0, 255],   # 3 sinkhole    magenta
            [255, 165,   0],   # 4 debris_flow orange
            [ 30,  30,  30],   # 5 background  dark
        ], dtype=np.uint8)

        N = min(len(images), 8)

        # Denormalize
        if mean is not None and std is not None:
            mean_arr = np.array(mean).reshape(1, 3, 1, 1)
            std_arr  = np.array(std).reshape(1, 3, 1, 1)
            imgs_show = images[:N] * std_arr + mean_arr
        else:
            imgs_show = images[:N]

        if imgs_show.shape[1] == 3:
            imgs_show = imgs_show.transpose(0, 2, 3, 1)
        imgs_show = np.clip(imgs_show, 0, 1)

        # If preds are logits (N, C, H, W), convert to class indices
        if preds.ndim == 4:
            preds = preds.argmax(axis=1)

        def to_color(label_map):
            return CLASS_COLORS[label_map.astype(np.int32)]

        fig, axes = plt.subplots(N, 3, figsize=(10, 3 * N))
        if N == 1:
            axes = axes[np.newaxis, :]

        for i in range(N):
            axes[i, 0].imshow(imgs_show[i])
            axes[i, 0].set_title("Image" if i == 0 else "")
            axes[i, 0].axis("off")

            axes[i, 1].imshow(to_color(masks[i]))
            axes[i, 1].set_title("Ground Truth" if i == 0 else "")
            axes[i, 1].axis("off")

            axes[i, 2].imshow(to_color(preds[i]))
            axes[i, 2].set_title("Prediction" if i == 0 else "")
            axes[i, 2].axis("off")

        title = "ViT-UNet Predictions"
        if epoch is not None:
            title += f" — Epoch {epoch}"
        fig.suptitle(title, fontsize=14, fontweight="bold")
        plt.tight_layout()

        if save_path is None:
            fname = f"predictions_epoch_{epoch:03d}.png" if epoch is not None else "predictions.png"
            save_path = os.path.join(self.output_dir, fname)
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[Visualizer] Prediction samples saved to {save_path}")

    # ── Confusion matrix ──────────────────────────────────

    def plot_confusion_matrix(self, tp: float = 0, fp: float = 0,
                              fn: float = 0, tn: float = 0,
                              conf_matrix: np.ndarray = None,
                              class_names=None, save_path: str = None):
        """Plot confusion matrix — accepts either 6x6 array or legacy tp/fp/fn/tn."""
        if conf_matrix is None:
            # Legacy binary fallback
            conf_matrix = np.array([[tn, fp], [fn, tp]], dtype=np.float64)
            class_names = class_names or ["Background", "Foreground"]
        else:
            conf_matrix = conf_matrix.astype(np.float64)
            if class_names is None:
                class_names = ["landslide", "crack", "rockfall",
                               "sinkhole", "debris_flow", "background"]

        cm_norm = conf_matrix / (conf_matrix.sum(axis=1, keepdims=True) + 1e-7)
        n = len(class_names)

        fig, axes = plt.subplots(1, 2, figsize=(max(10, n * 2), max(5, n)))

        for ax, data, title in [
            (axes[0], conf_matrix, "Counts"),
            (axes[1], cm_norm,     "Row-Normalized"),
        ]:
            im = ax.imshow(data, cmap="Blues", interpolation="nearest",
                           vmin=0, vmax=(1 if "Norm" in title else None))
            ax.set_title(f"Confusion Matrix ({title})", fontweight="bold")
            ax.set_xticks(range(n)); ax.set_xticklabels(class_names, rotation=45, ha="right")
            ax.set_yticks(range(n)); ax.set_yticklabels(class_names)
            ax.set_xlabel("Predicted"); ax.set_ylabel("True")
            for i in range(n):
                for j in range(n):
                    val = data[i, j]
                    txt = f"{val:.2f}" if "Norm" in title else f"{val:.0f}"
                    ax.text(j, i, txt, ha="center", va="center",
                            fontsize=max(6, 10 - n), fontweight="bold",
                            color="white" if val > data.max() * 0.6 else "black")
            plt.colorbar(im, ax=ax)

        fig.suptitle("ViT-UNet Confusion Matrix", fontsize=14, fontweight="bold")
        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, "confusion_matrix.png")
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[Visualizer] Confusion matrix saved to {save_path}")

    # ── Combined per-epoch dashboard ──────────────────────

    def plot_epoch_summary(self, epoch: int, history: dict,
                           images: np.ndarray, masks: np.ndarray,
                           preds: np.ndarray, tp: float, fp: float,
                           fn: float, tn: float, mean=None, std=None):
        """Save a comprehensive epoch summary figure."""
        # Training curves
        self.plot_training_curves(
            history,
            save_path=os.path.join(self.output_dir, "training_curves.png"),
        )
        # Predictions
        self.plot_predictions(
            images, masks, preds, epoch=epoch,
            save_path=os.path.join(self.output_dir, f"predictions_epoch_{epoch:03d}.png"),
            mean=mean, std=std,
        )
