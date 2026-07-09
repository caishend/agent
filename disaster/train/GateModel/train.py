"""
门控模型训练脚本
使用 BCEWithLogitsLoss（内部包含 Sigmoid）进行多标签分类训练

训练策略：
    Phase 1: 冻结 ResNet-50 backbone，仅训练分类头（warmup）
    Phase 2: 解冻 backbone，全模型微调
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torch.optim.lr_scheduler import CosineAnnealingLR, ReduceLROnPlateau
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    hamming_loss,
    classification_report,
)

from gating_dataset import GatingDataset
from gating_model import GatingModel


# ============ 配置 ============
def parse_args():
    parser = argparse.ArgumentParser(description="门控模型训练")
    parser.add_argument("--data_dir", type=str, default="new_dataset",
                        help="new_dataset 目录路径")
    parser.add_argument("--labels_csv", type=str, default="new_dataset/labels.csv",
                        help="labels.csv 文件路径")
    parser.add_argument("--output_dir", type=str, default="checkpoints",
                        help="模型保存目录")
    parser.add_argument("--batch_size", type=int, default=32,
                        help="批次大小")
    parser.add_argument("--epochs_phase1", type=int, default=10,
                        help="Phase1 epoch 数（冻结 backbone）")
    parser.add_argument("--epochs_phase2", type=int, default=30,
                        help="Phase2 epoch 数（全模型微调）")
    parser.add_argument("--lr_phase1", type=float, default=1e-3,
                        help="Phase1 学习率")
    parser.add_argument("--lr_phase2", type=float, default=1e-4,
                        help="Phase2 学习率")
    parser.add_argument("--weight_decay", type=float, default=1e-4,
                        help="权重衰减")
    parser.add_argument("--num_workers", type=int, default=4,
                        help="DataLoader 工作进程数")
    parser.add_argument("--device", type=str, default="auto",
                        help="设备: auto, cuda, cpu")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="分类阈值")
    parser.add_argument("--early_stopping_patience", type=int, default=7,
                        help="早停耐心值")
    parser.add_argument("--resume", type=str, default=None,
                        help="从检查点恢复训练")
    return parser.parse_args()


def set_seed(seed: int):
    """设置随机种子"""
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def get_device(device_str: str) -> torch.device:
    """获取设备"""
    if device_str == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device_str)


class EarlyStopping:
    """早停机制"""

    def __init__(self, patience: int = 7, min_delta: float = 0.0, mode: str = "min"):
        self.patience = patience
        self.min_delta = min_delta
        self.mode = mode
        self.counter = 0
        self.best_score = None
        self.early_stop = False

    def __call__(self, score: float) -> bool:
        if self.best_score is None:
            self.best_score = score
            return False

        if self.mode == "min":
            improved = score < self.best_score - self.min_delta
        else:
            improved = score > self.best_score + self.min_delta

        if improved:
            self.best_score = score
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.early_stop = True

        return improved


def compute_metrics(y_true, y_pred, y_prob=None):
    """
    计算多标签分类指标

    Args:
        y_true: (N, 3) 真实标签
        y_pred: (N, 3) 预测标签（阈值化后）
        y_prob: (N, 3) 预测概率（可选）
    Returns:
        dict: 各项指标
    """
    y_true_np = y_true.cpu().numpy()
    y_pred_np = y_pred.cpu().numpy()

    # 整体指标（sample-wise）
    metrics = {
        "subset_accuracy": accuracy_score(y_true_np, y_pred_np),
        "hamming_loss": hamming_loss(y_true_np, y_pred_np),
        "micro_precision": precision_score(y_true_np, y_pred_np, average="micro", zero_division=0),
        "micro_recall": recall_score(y_true_np, y_pred_np, average="micro", zero_division=0),
        "micro_f1": f1_score(y_true_np, y_pred_np, average="micro", zero_division=0),
        "macro_f1": f1_score(y_true_np, y_pred_np, average="macro", zero_division=0),
    }

    # 每个 group 的指标
    group_names = ["Group1(OD)", "Group2(Seg1)", "Group3(Seg2)"]
    for i, name in enumerate(group_names):
        metrics[f"{name}_precision"] = precision_score(
            y_true_np[:, i], y_pred_np[:, i], zero_division=0
        )
        metrics[f"{name}_recall"] = recall_score(
            y_true_np[:, i], y_pred_np[:, i], zero_division=0
        )
        metrics[f"{name}_f1"] = f1_score(
            y_true_np[:, i], y_pred_np[:, i], zero_division=0
        )

    return metrics


def train_epoch(model, dataloader, criterion, optimizer, device):
    """训练一个 epoch"""
    model.train()
    running_loss = 0.0
    all_preds = []
    all_labels = []
    all_probs = []

    for images, labels in dataloader:
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        logits = model(images)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()

        running_loss += loss.item() * images.size(0)
        probs = torch.sigmoid(logits)
        preds = (probs >= 0.5).float()

        all_preds.append(preds.detach().cpu())
        all_labels.append(labels.detach().cpu())
        all_probs.append(probs.detach().cpu())

    epoch_loss = running_loss / len(dataloader.dataset)
    all_preds = torch.cat(all_preds)
    all_labels = torch.cat(all_labels)
    all_probs = torch.cat(all_probs)

    metrics = compute_metrics(all_labels, all_preds, all_probs)
    metrics["loss"] = epoch_loss

    return metrics


@torch.no_grad()
def validate_epoch(model, dataloader, criterion, device):
    """验证一个 epoch"""
    model.eval()
    running_loss = 0.0
    all_preds = []
    all_labels = []
    all_probs = []

    for images, labels in dataloader:
        images = images.to(device)
        labels = labels.to(device)

        logits = model(images)
        loss = criterion(logits, labels)

        running_loss += loss.item() * images.size(0)
        probs = torch.sigmoid(logits)
        preds = (probs >= 0.5).float()

        all_preds.append(preds.cpu())
        all_labels.append(labels.cpu())
        all_probs.append(probs.cpu())

    epoch_loss = running_loss / len(dataloader.dataset)
    all_preds = torch.cat(all_preds)
    all_labels = torch.cat(all_labels)
    all_probs = torch.cat(all_probs)

    metrics = compute_metrics(all_labels, all_preds, all_probs)
    metrics["loss"] = epoch_loss

    return metrics


def print_metrics(phase: str, epoch: int, metrics: dict, total_epochs: int):
    """打印指标"""
    print(f"\n{'='*60}")
    print(f"[{phase}] Epoch {epoch+1}/{total_epochs}")
    print(f"{'='*60}")
    print(f"  Loss:              {metrics['loss']:.4f}")
    print(f"  Subset Accuracy:   {metrics['subset_accuracy']:.4f}")
    print(f"  Hamming Loss:      {metrics['hamming_loss']:.4f}")
    print(f"  Micro F1:          {metrics['micro_f1']:.4f}")
    print(f"  Macro F1:          {metrics['macro_f1']:.4f}")
    print(f"  --- Per Group ---")
    for name in ["Group1(OD)", "Group2(Seg1)", "Group3(Seg2)"]:
        print(f"  {name:20s} P={metrics[f'{name}_precision']:.4f}  "
              f"R={metrics[f'{name}_recall']:.4f}  "
              f"F1={metrics[f'{name}_f1']:.4f}")


def train_phase(
    model,
    train_loader,
    val_loader,
    criterion,
    optimizer,
    scheduler,
    device,
    num_epochs: int,
    phase_name: str,
    output_dir: Path,
    early_stopping_patience: int,
):
    """训练一个阶段"""
    early_stopping = EarlyStopping(patience=early_stopping_patience, mode="min")
    best_val_f1 = 0.0
    history = {"train": [], "val": []}

    for epoch in range(num_epochs):
        # 训练
        train_metrics = train_epoch(model, train_loader, criterion, optimizer, device)
        history["train"].append(train_metrics)

        # 验证
        val_metrics = validate_epoch(model, val_loader, criterion, device)
        history["val"].append(val_metrics)

        # 学习率调整
        if isinstance(scheduler, ReduceLROnPlateau):
            scheduler.step(val_metrics["loss"])
        else:
            scheduler.step()

        # 打印
        print_metrics(phase_name, epoch, val_metrics, num_epochs)

        # 保存最佳模型
        if val_metrics["micro_f1"] > best_val_f1:
            best_val_f1 = val_metrics["micro_f1"]
            checkpoint = {
                "epoch": epoch,
                "phase": phase_name,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_metrics": val_metrics,
                "best_val_f1": best_val_f1,
            }
            torch.save(checkpoint, output_dir / "best_model.pth")
            print(f"  [>>>] 保存最佳模型 (micro_f1={best_val_f1:.4f})")

        # 早停检查
        improved = early_stopping(val_metrics["loss"])
        if early_stopping.early_stop:
            print(f"\n[早停] {phase_name} 在第 {epoch+1} 个 epoch 触发早停")
            break

    return history, best_val_f1


def main():
    args = parse_args()
    set_seed(args.seed)

    # 设备
    device = get_device(args.device)
    print(f"设备: {device}")

    # 输出目录
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 日志
    log_file = output_dir / f"training_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    # 保存配置
    config = vars(args)
    config["timestamp"] = datetime.now().isoformat()
    with open(output_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    # ============ 数据加载 ============
    print("\n" + "=" * 60)
    print("加载数据集")
    print("=" * 60)

    train_dataset = GatingDataset(
        args.data_dir, args.labels_csv, split="train",
        train_ratio=0.7, val_ratio=0.15, seed=args.seed,
    )
    val_dataset = GatingDataset(
        args.data_dir, args.labels_csv, split="val",
        train_ratio=0.7, val_ratio=0.15, seed=args.seed,
    )
    test_dataset = GatingDataset(
        args.data_dir, args.labels_csv, split="test",
        train_ratio=0.7, val_ratio=0.15, seed=args.seed,
    )

    print(f"训练集: {train_dataset.get_split_info()}")
    print(f"验证集: {val_dataset.get_split_info()}")
    print(f"测试集: {test_dataset.get_split_info()}")

    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True,
        num_workers=args.num_workers, pin_memory=True,
    )
    val_loader = DataLoader(
        val_dataset, batch_size=args.batch_size, shuffle=False,
        num_workers=args.num_workers, pin_memory=True,
    )
    test_loader = DataLoader(
        test_dataset, batch_size=args.batch_size, shuffle=False,
        num_workers=args.num_workers, pin_memory=True,
    )

    # ============ 模型 ============
    print("\n" + "=" * 60)
    print("创建模型")
    print("=" * 60)

    model = GatingModel(num_groups=3, pretrained=True, freeze_backbone=True)
    model = model.to(device)
    print(f"总参数量: {sum(p.numel() for p in model.parameters()):,}")
    print(f"可训练参数量: {sum(p.numel() for p in model.parameters() if p.requires_grad):,}")

    # 损失函数（使用 pos_weight 处理类别不平衡）
    pos_weight = train_dataset.get_class_weights().to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    print(f"pos_weight: {pos_weight}")

    # ============ Phase 1: 训练分类头 ============
    print("\n" + "=" * 60)
    print("Phase 1: 训练分类头（冻结 ResNet backbone）")
    print("=" * 60)

    optimizer = optim.AdamW(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=args.lr_phase1,
        weight_decay=args.weight_decay,
    )
    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs_phase1)

    history_phase1, best_f1_p1 = train_phase(
        model, train_loader, val_loader, criterion, optimizer, scheduler,
        device, args.epochs_phase1, "Phase1", output_dir, args.early_stopping_patience,
    )

    # ============ Phase 2: 全模型微调 ============
    print("\n" + "=" * 60)
    print("Phase 2: 全模型微调（解冻 backbone）")
    print("=" * 60)

    # 解冻 backbone
    for param in model.backbone.parameters():
        param.requires_grad = True

    # 使用更小的学习率
    optimizer = optim.AdamW(
        [
            {"params": model.backbone.fc.parameters(), "lr": args.lr_phase2 * 10},
            {"params": model.backbone.layer4.parameters(), "lr": args.lr_phase2},
            {"params": model.backbone.layer3.parameters(), "lr": args.lr_phase2 * 0.5},
            {"params": model.backbone.layer2.parameters(), "lr": args.lr_phase2 * 0.1},
            {"params": model.backbone.layer1.parameters(), "lr": args.lr_phase2 * 0.1},
            {"params": model.backbone.conv1.parameters(), "lr": args.lr_phase2 * 0.01},
            {"params": model.backbone.bn1.parameters(), "lr": args.lr_phase2 * 0.01},
        ],
        weight_decay=args.weight_decay,
    )
    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs_phase2)

    print(f"可训练参数量: {sum(p.numel() for p in model.parameters() if p.requires_grad):,}")

    history_phase2, best_f1_p2 = train_phase(
        model, train_loader, val_loader, criterion, optimizer, scheduler,
        device, args.epochs_phase2, "Phase2", output_dir, args.early_stopping_patience,
    )

    # ============ 最终评估 ============
    print("\n" + "=" * 60)
    print("加载最佳模型并在测试集上评估")
    print("=" * 60)

    # 加载最佳模型
    best_checkpoint = torch.load(output_dir / "best_model.pth", map_location=device, weights_only=False)
    model.load_state_dict(best_checkpoint["model_state_dict"])
    print(f"加载最佳模型: epoch={best_checkpoint['epoch']}, val_f1={best_checkpoint['best_val_f1']:.4f}")

    # 测试集评估
    test_metrics = validate_epoch(model, test_loader, criterion, device)
    print(f"\n{'='*60}")
    print("测试集结果")
    print(f"{'='*60}")
    print(f"  Subset Accuracy:   {test_metrics['subset_accuracy']:.4f}")
    print(f"  Hamming Loss:      {test_metrics['hamming_loss']:.4f}")
    print(f"  Micro F1:          {test_metrics['micro_f1']:.4f}")
    print(f"  Macro F1:          {test_metrics['macro_f1']:.4f}")
    print(f"  --- Per Group ---")
    for name in ["Group1(OD)", "Group2(Seg1)", "Group3(Seg2)"]:
        print(f"  {name:20s} P={test_metrics[f'{name}_precision']:.4f}  "
              f"R={test_metrics[f'{name}_recall']:.4f}  "
              f"F1={test_metrics[f'{name}_f1']:.4f}")

    # 保存全部训练历史
    all_history = {
        "config": config,
        "phase1": history_phase1,
        "phase2": history_phase2,
        "test_metrics": {k: float(v) if isinstance(v, (np.floating, torch.Tensor)) else v
                         for k, v in test_metrics.items()},
    }
    with open(log_file, "w") as f:
        json.dump(all_history, f, indent=2, ensure_ascii=False)
    print(f"\n训练历史已保存到: {log_file}")

    # 导出最终模型（仅模型权重，不含优化器状态）
    final_model_path = output_dir / "gating_model_final.pth"
    torch.save({
        "model_state_dict": model.state_dict(),
        "threshold": args.threshold,
        "config": config,
    }, final_model_path)
    print(f"最终模型已保存到: {final_model_path}")


if __name__ == "__main__":
    main()
