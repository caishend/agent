from pathlib import Path

import torch
from ultralytics import YOLO


ROOT = Path(r"D:\nyx66666")
DATA_YAML = ROOT / "merged_yolo_8_1_1" / "data_full_balanced.yaml"
RUN_DIR_CANDIDATES = [
    ROOT / "runs_detect" / "yolo11m_target_p90_r85_v3",
    ROOT / "runs_detect" / "yolo11m_merged_full_balanced_v2",
    ROOT / "runs_detect" / "yolo11m_merged_full_balanced",
    ROOT / "runs_detect" / "yolo11m_merged_20",
]
CLASS_NAMES = ["snow", "water_accumulation", "flood"]

BATCH = 8
DEVICE = 0
IMGSZ = 640
WORKERS = 0
CONF_SWEEP = [0.001, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
TARGET_PRECISION = 0.90
TARGET_RECALL = 0.85


def print_metrics(title: str, metrics) -> None:
    box = metrics.box

    print("\n" + "=" * 80)
    print(f"{title} METRICS")
    print("-" * 80)
    print("Overall:")
    print(f"  Precision: {box.mp:.4f}")
    print(f"  Recall:    {box.mr:.4f}")
    print(f"  mAP50:     {box.map50:.4f}")
    print(f"  mAP50-95:  {box.map:.4f}")

    per_class_precision = [float("nan")] * len(CLASS_NAMES)
    per_class_recall = [float("nan")] * len(CLASS_NAMES)
    per_class_map50 = [float("nan")] * len(CLASS_NAMES)
    per_class_map = [float("nan")] * len(CLASS_NAMES)

    class_indices = list(getattr(box, "ap_class_index", range(len(box.maps))))
    for source_idx, class_idx in enumerate(class_indices):
        class_idx = int(class_idx)
        if class_idx >= len(CLASS_NAMES):
            continue
        if source_idx < len(box.p):
            per_class_precision[class_idx] = box.p[source_idx]
        if source_idx < len(box.r):
            per_class_recall[class_idx] = box.r[source_idx]
        if source_idx < len(box.ap50):
            per_class_map50[class_idx] = box.ap50[source_idx]
        if class_idx < len(box.maps):
            per_class_map[class_idx] = box.maps[class_idx]

    print("\nPer-class:")
    print("id  class                 precision  recall     mAP50      mAP50-95")
    for idx, name in enumerate(CLASS_NAMES):
        print(
            f"{idx:<3} {name:<21} "
            f"{per_class_precision[idx]:<10.4f} "
            f"{per_class_recall[idx]:<10.4f} "
            f"{per_class_map50[idx]:<10.4f} "
            f"{per_class_map[idx]:<10.4f}"
        )


def short_metrics(metrics) -> tuple[float, float, float, float]:
    box = metrics.box
    return box.mp, box.mr, box.map50, box.map


def run_conf_sweep(model: YOLO, split: str) -> None:
    print("\n" + "=" * 80)
    print(f"{split.upper()} CONFIDENCE SWEEP")
    print("-" * 80)
    print("conf      precision  recall     mAP50      mAP50-95   target")

    best_f1 = None
    best_row = None
    target_rows = []
    for conf in CONF_SWEEP:
        metrics = model.val(
            data=str(DATA_YAML),
            split=split,
            imgsz=IMGSZ,
            batch=BATCH,
            device=DEVICE,
            workers=WORKERS,
            conf=conf,
            verbose=False,
            plots=False,
        )
        precision, recall, map50, map95 = short_metrics(metrics)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        hit = precision >= TARGET_PRECISION and recall >= TARGET_RECALL
        marker = "YES" if hit else ""
        print(f"{conf:<9.3f} {precision:<10.4f} {recall:<10.4f} {map50:<10.4f} {map95:<10.4f} {marker}")
        if best_f1 is None or f1 > best_f1:
            best_f1 = f1
            best_row = (conf, precision, recall, map50, map95, f1)
        if hit:
            target_rows.append((conf, precision, recall, map50, map95))

    if best_row:
        conf, precision, recall, map50, map95, f1 = best_row
        print(
            f"\nBest F1 threshold: conf={conf:.3f}, "
            f"P={precision:.4f}, R={recall:.4f}, mAP50={map50:.4f}, mAP50-95={map95:.4f}, F1={f1:.4f}"
        )
    if not target_rows:
        print(f"No threshold in sweep reached P>={TARGET_PRECISION:.2f} and R>={TARGET_RECALL:.2f}.")


def main() -> None:
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(DEVICE)}")

    weights = None
    run_dir = None
    for candidate in RUN_DIR_CANDIDATES:
        best = candidate / "weights" / "best.pt"
        last = candidate / "weights" / "last.pt"
        if best.exists():
            weights = best
            run_dir = candidate
            break
        if last.exists():
            weights = last
            run_dir = candidate
            break
    if weights is None:
        searched = "\n".join(str(path / "weights") for path in RUN_DIR_CANDIDATES)
        raise FileNotFoundError(f"No weights found. Searched:\n{searched}")

    print(f"Run dir: {run_dir}")
    print(f"Weights: {weights}")
    print(f"Data yaml: {DATA_YAML}")
    print(f"Eval workers: {WORKERS}")

    model = YOLO(str(weights))
    print_metrics(
        "VALIDATION",
        model.val(data=str(DATA_YAML), split="val", imgsz=IMGSZ, batch=BATCH, device=DEVICE, workers=WORKERS),
    )
    print_metrics(
        "TEST",
        model.val(data=str(DATA_YAML), split="test", imgsz=IMGSZ, batch=BATCH, device=DEVICE, workers=WORKERS),
    )
    run_conf_sweep(model, "val")
    run_conf_sweep(model, "test")


if __name__ == "__main__":
    main()
