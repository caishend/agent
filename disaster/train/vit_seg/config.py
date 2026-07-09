"""Configuration for ViT-Small segmentation."""

import os
import sys

os.environ.setdefault("TIMM_DISABLE_DOWNLOAD", "1")   # offline: no accidental downloads

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Default path: look next to this folder (same layout as the reference script)
_PRETRAINED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pretrained")


class ViTSegConfig:
    # ── Paths ──────────────────────────────────────────────
    ROOT_DIR       = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR       = os.path.join(PROJECT_ROOT, "merged_five_clean")
    OUTPUT_DIR     = os.path.join(ROOT_DIR, "outputs")
    CHECKPOINT_DIR = os.path.join(OUTPUT_DIR, "checkpoints")
    LOG_DIR        = os.path.join(OUTPUT_DIR, "logs")

    # Local .pth file for the ViT-Small pretrained weights.
    # Adjust this path to wherever you placed vit_small_patch16_224.pth.
    VIT_CKPT = os.path.join(_PRETRAINED_DIR, "vit_small_patch16_224.pth")

    # ── Data ───────────────────────────────────────────────
    IMAGE_SIZE  = 512       # 512 / 16 = 32×32 patch grid; pos_embed is resized at load time
    BATCH_SIZE  = 8
    NUM_WORKERS = 0
    MEAN = [0.485, 0.456, 0.406]
    STD  = [0.229, 0.224, 0.225]

    # ── Model ──────────────────────────────────────────────
    NUM_CLASSES = 6
    CLASS_NAMES = ["landslide", "crack", "rockfall", "sinkhole", "debris_flow", "background"]

    # ── Training ───────────────────────────────────────────
    EPOCHS              = 100
    WEIGHT_DECAY        = 1e-2
    LR_WARMUP_EPOCHS    = 5
    LR_MIN              = 1e-6
    EARLY_STOP_PATIENCE = 20
    LR_BACKBONE         = 1e-4
    LR_HEAD             = 5e-4

    # Loss weights
    CE_WEIGHT   = 0.5
    DICE_WEIGHT = 0.5

    # ── Hardware ───────────────────────────────────────────
    DEVICE = "cuda"

    # ── Logging ────────────────────────────────────────────
    VIZ_SAMPLES = 4

    @classmethod
    def create_dirs(cls):
        for d in [cls.OUTPUT_DIR, cls.CHECKPOINT_DIR, cls.LOG_DIR]:
            os.makedirs(d, exist_ok=True)


config = ViTSegConfig()
