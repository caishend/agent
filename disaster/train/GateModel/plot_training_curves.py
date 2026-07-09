"""
训练过程可视化脚本
读取 checkpoints/training_log_20260612_234717.json 并生成连续的训练曲线图

输出: checkpoints/training_curves.png
"""

import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 非交互式后端，避免在没有 GUI 的环境下报错
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.font_manager as fm
import numpy as np

# ---- 中文字体自动检测 ----
_CJK_CANDIDATES = [
    "Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "FangSong",
    "Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei", "AR PL UMing CN", "AR PL UKai CN",
]
_available_fonts = {f.name for f in fm.fontManager.ttflist}
_cjk_font = None
for _font_name in _CJK_CANDIDATES:
    if _font_name in _available_fonts:
        _cjk_font = _font_name
        break

if _cjk_font:
    plt.rcParams["font.family"] = _cjk_font
    print(f"[INFO] 使用中文字体: {_cjk_font}")
else:
    print("[WARN] 未找到中文字体，标题中的中文可能无法正常显示")

# ============ 配置 ============
LOG_FILE = Path(__file__).parent / "checkpoints" / "training_log_20260612_234717.json"
OUTPUT_FILE = Path(__file__).parent / "checkpoints" / "training_curves.png"

# 全局绘图风格
plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "legend.fontsize": 8,
    "lines.linewidth": 1.5,
    "lines.markersize": 3,
})

# 配色方案 (tab10 风格，美观且区分度高)
COLORS = {
    "train":       "#1f77b4",  # 蓝色
    "val":         "#ff7f0e",  # 橙色
    "phase1":      "#2ca02c",  # 绿色
    "phase2":      "#d62728",  # 红色
    "group1":      "#1f77b4",  # 蓝色
    "group2":      "#ff7f0e",  # 橙色
    "group3":      "#2ca02c",  # 绿色
    "micro_f1":    "#9467bd",  # 紫色
    "macro_f1":    "#8c564b",  # 棕色
    "phase_boundary": "#999999",  # 灰色
}


def load_training_log(log_path: Path) -> dict:
    """加载训练日志 JSON 文件"""
    with open(log_path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_phase_epochs(phase1_data: list, phase2_data: list):
    """
    将两个阶段的 epoch 数据合并为连续的序列

    Returns:
        epochs:      连续 epoch 编号列表 (0-based → 转为 1-based)
        phase1_count: 第一阶段 epoch 数量
        phase2_count: 第二阶段 epoch 数量
    """
    p1_count = len(phase1_data)
    p2_count = len(phase2_data)
    total = p1_count + p2_count
    epochs = list(range(1, total + 1))
    return epochs, p1_count, p2_count


def extract_metric(phase1_list: list, phase2_list: list, metric_name: str):
    """
    从两个阶段的列表中提取指定指标，合并为连续数组

    如果 metric 在 phase2 中不存在，则用 phase1 的最后一个值填充缺失部分。
    """
    p1_vals = [entry[metric_name] for entry in phase1_list]
    p2_vals = [entry[metric_name] for entry in phase2_list]
    return p1_vals + p2_vals


def plot_all_curves(data: dict, output_path: Path):
    """绘制全部训练曲线"""
    phase1 = data["phase1"]
    phase2 = data["phase2"]
    config = data["config"]

    # 合并数据
    epochs, p1_count, p2_count = merge_phase_epochs(phase1["train"], phase2["train"])

    # 提取各指标
    train_loss = extract_metric(phase1["train"], phase2["train"], "loss")
    val_loss   = extract_metric(phase1["val"],   phase2["val"],   "loss")

    train_micro_f1 = extract_metric(phase1["train"], phase2["train"], "micro_f1")
    val_micro_f1   = extract_metric(phase1["val"],   phase2["val"],   "micro_f1")

    train_macro_f1 = extract_metric(phase1["train"], phase2["train"], "macro_f1")
    val_macro_f1   = extract_metric(phase1["val"],   phase2["val"],   "macro_f1")

    train_acc = extract_metric(phase1["train"], phase2["train"], "subset_accuracy")
    val_acc   = extract_metric(phase1["val"],   phase2["val"],   "subset_accuracy")

    train_hl = extract_metric(phase1["train"], phase2["train"], "hamming_loss")
    val_hl   = extract_metric(phase1["val"],   phase2["val"],   "hamming_loss")

    # Per-group F1 (仅验证集)
    val_g1_f1 = extract_metric(phase1["val"], phase2["val"], "Group1(OD)_f1")
    val_g2_f1 = extract_metric(phase1["val"], phase2["val"], "Group2(Seg1)_f1")
    val_g3_f1 = extract_metric(phase1["val"], phase2["val"], "Group3(Seg2)_f1")

    train_g1_f1 = extract_metric(phase1["train"], phase2["train"], "Group1(OD)_f1")
    train_g2_f1 = extract_metric(phase1["train"], phase2["train"], "Group2(Seg1)_f1")
    train_g3_f1 = extract_metric(phase1["train"], phase2["train"], "Group3(Seg2)_f1")

    # ========== 创建画布 ==========
    fig = plt.figure(figsize=(20, 14))

    # 使用 GridSpec 布局
    gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.30,
                          top=0.93, bottom=0.06, left=0.06, right=0.98)

    # ---- (1) Loss 曲线 ----
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(epochs, train_loss, color=COLORS["train"], marker=".", label="Train Loss")
    ax1.plot(epochs, val_loss,   color=COLORS["val"],   marker=".", label="Val Loss")
    ax1.axvline(x=p1_count + 0.5, color=COLORS["phase_boundary"],
                linestyle="--", linewidth=1.2, alpha=0.7)
    ax1.text(p1_count / 2, ax1.get_ylim()[1] * 0.95 if train_loss else 0.5,
             "Phase 1\n(Frozen Backbone)", ha="center", fontsize=7,
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#e8f5e9", alpha=0.8))
    ax1.text(p1_count + p2_count / 2, ax1.get_ylim()[1] * 0.95 if train_loss else 0.5,
             "Phase 2\n(Full Fine-tune)", ha="center", fontsize=7,
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#fce4ec", alpha=0.8))
    ax1.set_xlabel("Epoch")
    ax1.set_ylabel("Loss")
    ax1.set_title("Training & Validation Loss")
    ax1.legend(loc="upper right")
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(1, len(epochs))

    # ---- (2) Micro F1 曲线 ----
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(epochs, train_micro_f1, color=COLORS["train"], marker=".", label="Train Micro F1")
    ax2.plot(epochs, val_micro_f1,   color=COLORS["val"],   marker=".", label="Val Micro F1")
    ax2.axvline(x=p1_count + 0.5, color=COLORS["phase_boundary"],
                linestyle="--", linewidth=1.2, alpha=0.7)
    ax2.set_xlabel("Epoch")
    ax2.set_ylabel("Micro F1")
    ax2.set_title("Micro F1 Score")
    ax2.legend(loc="lower right")
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(1, len(epochs))

    # ---- (3) Subset Accuracy 曲线 ----
    ax3 = fig.add_subplot(gs[0, 2])
    ax3.plot(epochs, train_acc, color=COLORS["train"], marker=".", label="Train Acc")
    ax3.plot(epochs, val_acc,   color=COLORS["val"],   marker=".", label="Val Acc")
    ax3.axvline(x=p1_count + 0.5, color=COLORS["phase_boundary"],
                linestyle="--", linewidth=1.2, alpha=0.7)
    ax3.set_xlabel("Epoch")
    ax3.set_ylabel("Subset Accuracy")
    ax3.set_title("Subset Accuracy (Exact Match)")
    ax3.legend(loc="lower right")
    ax3.grid(True, alpha=0.3)
    ax3.set_xlim(1, len(epochs))

    # ---- (4) Hamming Loss 曲线 ----
    ax4 = fig.add_subplot(gs[1, 0])
    ax4.plot(epochs, train_hl, color=COLORS["train"], marker=".", label="Train HL")
    ax4.plot(epochs, val_hl,   color=COLORS["val"],   marker=".", label="Val HL")
    ax4.axvline(x=p1_count + 0.5, color=COLORS["phase_boundary"],
                linestyle="--", linewidth=1.2, alpha=0.7)
    ax4.set_xlabel("Epoch")
    ax4.set_ylabel("Hamming Loss")
    ax4.set_title("Hamming Loss")
    ax4.legend(loc="upper right")
    ax4.grid(True, alpha=0.3)
    ax4.set_xlim(1, len(epochs))

    # ---- (5) Macro F1 曲线 ----
    ax5 = fig.add_subplot(gs[1, 1])
    ax5.plot(epochs, train_macro_f1, color=COLORS["train"], marker=".", label="Train Macro F1")
    ax5.plot(epochs, val_macro_f1,   color=COLORS["val"],   marker=".", label="Val Macro F1")
    ax5.axvline(x=p1_count + 0.5, color=COLORS["phase_boundary"],
                linestyle="--", linewidth=1.2, alpha=0.7)
    ax5.set_xlabel("Epoch")
    ax5.set_ylabel("Macro F1")
    ax5.set_title("Macro F1 Score")
    ax5.legend(loc="lower right")
    ax5.grid(True, alpha=0.3)
    ax5.set_xlim(1, len(epochs))

    # ---- (6) Per-Group F1 (验证集) ----
    ax6 = fig.add_subplot(gs[1, 2])
    ax6.plot(epochs, val_g1_f1, color=COLORS["group1"], marker=".", label="Group1 (OD)")
    ax6.plot(epochs, val_g2_f1, color=COLORS["group2"], marker=".", label="Group2 (Seg1)")
    ax6.plot(epochs, val_g3_f1, color=COLORS["group3"], marker=".", label="Group3 (Seg2)")
    ax6.axvline(x=p1_count + 0.5, color=COLORS["phase_boundary"],
                linestyle="--", linewidth=1.2, alpha=0.7)
    ax6.set_xlabel("Epoch")
    ax6.set_ylabel("F1 Score")
    ax6.set_title("Per-Group F1 (Validation)")
    ax6.legend(loc="lower right")
    ax6.grid(True, alpha=0.3)
    ax6.set_xlim(1, len(epochs))

    # ---- (7) Per-Group F1 (训练集) ----
    ax7 = fig.add_subplot(gs[2, 0])
    ax7.plot(epochs, train_g1_f1, color=COLORS["group1"], marker=".", label="Group1 (OD)")
    ax7.plot(epochs, train_g2_f1, color=COLORS["group2"], marker=".", label="Group2 (Seg1)")
    ax7.plot(epochs, train_g3_f1, color=COLORS["group3"], marker=".", label="Group3 (Seg2)")
    ax7.axvline(x=p1_count + 0.5, color=COLORS["phase_boundary"],
                linestyle="--", linewidth=1.2, alpha=0.7)
    ax7.set_xlabel("Epoch")
    ax7.set_ylabel("F1 Score")
    ax7.set_title("Per-Group F1 (Training)")
    ax7.legend(loc="lower right")
    ax7.grid(True, alpha=0.3)
    ax7.set_xlim(1, len(epochs))

    # ---- (8) 最终测试集结果条形图 ----
    ax8 = fig.add_subplot(gs[2, 1])
    test_metrics = data["test_metrics"]
    test_groups = ["Group1\n(OD)", "Group2\n(Seg1)", "Group3\n(Seg2)"]
    test_p = [test_metrics["Group1(OD)_precision"],
              test_metrics["Group2(Seg1)_precision"],
              test_metrics["Group3(Seg2)_precision"]]
    test_r = [test_metrics["Group1(OD)_recall"],
              test_metrics["Group2(Seg1)_recall"],
              test_metrics["Group3(Seg2)_recall"]]
    test_f1 = [test_metrics["Group1(OD)_f1"],
               test_metrics["Group2(Seg1)_f1"],
               test_metrics["Group3(Seg2)_f1"]]

    x_pos = np.arange(len(test_groups))
    bar_width = 0.25
    bars_p = ax8.bar(x_pos - bar_width, test_p, bar_width,
                     color="#5c9bd5", edgecolor="white", label="Precision")
    bars_r = ax8.bar(x_pos,             test_r, bar_width,
                     color="#ed7d31", edgecolor="white", label="Recall")
    bars_f1 = ax8.bar(x_pos + bar_width, test_f1, bar_width,
                      color="#70ad47", edgecolor="white", label="F1")

    # 在柱上标注数值
    for bar in bars_p:
        ax8.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.003,
                 f"{bar.get_height():.3f}", ha="center", fontsize=6.5)
    for bar in bars_r:
        ax8.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.003,
                 f"{bar.get_height():.3f}", ha="center", fontsize=6.5)
    for bar in bars_f1:
        ax8.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.003,
                 f"{bar.get_height():.3f}", ha="center", fontsize=6.5)

    ax8.set_xticks(x_pos)
    ax8.set_xticklabels(test_groups)
    ax8.set_ylabel("Score")
    ax8.set_title("Test Set Per-Group Metrics")
    ax8.legend(loc="lower right")
    ax8.set_ylim(0.90, 1.04)
    ax8.grid(True, alpha=0.2, axis="y")

    # ---- (9) 训练超参数 & 关键结果汇总 ----
    ax9 = fig.add_subplot(gs[2, 2])
    ax9.axis("off")

    summary_lines = [
        "═══ Training Summary ═══",
        "",
        f"Batch Size:        {config['batch_size']}",
        f"Phase1 Epochs:     {config['epochs_phase1']} (frozen backbone)",
        f"Phase2 Epochs:     {config['epochs_phase2']} (full fine-tune)",
        f"LR Phase1:         {config['lr_phase1']}",
        f"LR Phase2:         {config['lr_phase2']}",
        f"Optimizer:         AdamW",
        f"LR Scheduler:      CosineAnnealingLR",
        f"Early Stop Pat.:   {config['early_stopping_patience']}",
        "",
        "═══ Final Test Results ═══",
        "",
        f"Subset Accuracy:   {test_metrics['subset_accuracy']:.4f}",
        f"Hamming Loss:      {test_metrics['hamming_loss']:.4f}",
        f"Micro F1:          {test_metrics['micro_f1']:.4f}",
        f"Macro F1:          {test_metrics['macro_f1']:.4f}",
        f"Test Loss:         {test_metrics['loss']:.4f}",
        "",
        "═══ Best Val (Phase2) ═══",
        f"Best Val Micro F1: {max(val_micro_f1[p1_count:]):.4f}",
        f"Best Val Loss:     {min(val_loss[p1_count:]):.4f}",
    ]

    for i, line in enumerate(summary_lines):
        y_pos = 1.0 - i * 0.042
        if line.startswith("═══"):
            ax9.text(0.05, y_pos, line, fontsize=9, fontweight="bold",
                     fontfamily="monospace", color="#333333",
                     transform=ax9.transAxes)
        elif line == "":
            pass
        else:
            ax9.text(0.08, y_pos, line, fontsize=8, fontfamily="monospace",
                     color="#555555", transform=ax9.transAxes)

    # ========== 全局标题 ==========
    fig.suptitle(
        f"管道巡检门控模型训练曲线\n"
        f"Gating Model Training Curves — {config['timestamp'][:19]}",
        fontsize=14, fontweight="bold", y=0.98,
    )

    # ========== 保存 ==========
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    print(f"[OK] 训练曲线图已保存到: {output_path}")


def main():
    if not LOG_FILE.exists():
        print(f"[ERROR] 训练日志文件不存在: {LOG_FILE}")
        print("请确认 checkpoints/training_log_20260612_234717.json 存在")
        return

    print(f"[INFO] 加载训练日志: {LOG_FILE}")
    data = load_training_log(LOG_FILE)

    print(f"[INFO] Phase1: {len(data['phase1']['train'])} train epochs, "
          f"{len(data['phase1']['val'])} val epochs")
    print(f"[INFO] Phase2: {len(data['phase2']['train'])} train epochs, "
          f"{len(data['phase2']['val'])} val epochs")
    print(f"[INFO] Test Metrics: Subset Acc={data['test_metrics']['subset_accuracy']:.4f}, "
          f"Micro F1={data['test_metrics']['micro_f1']:.4f}")

    print(f"[INFO] 正在绘制训练曲线...")
    plot_all_curves(data, OUTPUT_FILE)

    print("[DONE] 可视化完成!")


if __name__ == "__main__":
    main()
