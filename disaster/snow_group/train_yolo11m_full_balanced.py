import csv
import math
from collections import Counter, defaultdict
from pathlib import Path

import torch
from ultralytics import YOLO


ROOT = Path(r"D:\nyx66666")
DATASET_DIR = ROOT / "merged_yolo_8_1_1"
MODEL_PATH = ROOT / "yolo11m.pt"
V2_BEST_MODEL_PATH = ROOT / "runs_detect" / "yolo11m_merged_full_balanced_v2" / "weights" / "best.pt"
RUNS_DIR = ROOT / "runs_detect"
RUN_NAME = "yolo11m_target_p90_r85_v3"
RUN_DIR = RUNS_DIR / RUN_NAME
RESUME_IF_AVAILABLE = True

CLASS_NAMES = ["snow", "water_accumulation", "flood"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

EPOCHS = 100
IMGSZ = 768
BATCH = 4
DEVICE = 0
WORKERS = 4
EVAL_WORKERS = 0
PATIENCE = 30
MAX_REPEAT = 4
CACHE = "ram"
DETERMINISTIC = False

# These targets are applied after every original training image is included once.
# The builder then adds only the samples needed to close each class deficit.
TARGET_OBJECT_MULTIPLIER = {
    0: 1.70,  # snow recall is still low
    1: 1.70,  # water_accumulation needs stronger recall
    2: 1.25,  # flood is already strongest
}


def read_label_counts(label_path: Path) -> Counter:
    counts = Counter()
    if not label_path.exists():
        return counts
    for line in label_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        class_id = line.split()[0]
        if class_id in {"0", "1", "2"}:
            counts[int(class_id)] += 1
    return counts


def image_to_label(image_path: Path, split: str) -> Path:
    return DATASET_DIR / split / "labels" / f"{image_path.stem}.txt"


def collect_split_stats(split: str) -> tuple[list[dict], Counter, Counter, int]:
    image_dir = DATASET_DIR / split / "images"
    images = sorted(p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    samples = []
    object_counts = Counter()
    image_counts = Counter()
    empty_images = 0

    for image_path in images:
        label_path = image_to_label(image_path, split)
        label_counts = read_label_counts(label_path)
        classes = set(label_counts)
        object_counts.update(label_counts)
        for class_id in classes:
            image_counts[class_id] += 1
        if not classes:
            empty_images += 1
        samples.append({"image": image_path, "label_counts": label_counts, "classes": classes})

    return samples, object_counts, image_counts, empty_images


def print_distribution(title: str, image_total: int, empty_images: int, object_counts: Counter, image_counts: Counter) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("-" * 80)
    print(f"Images: {image_total}")
    print(f"Empty-label images: {empty_images}")
    print("\nClass distribution:")
    print("id  class                 objects   images_with_class")
    for class_id, name in enumerate(CLASS_NAMES):
        print(f"{class_id:<3} {name:<21} {object_counts[class_id]:<9} {image_counts[class_id]}")


def build_balanced_train_list() -> tuple[Path, Counter, Counter, int]:
    samples, object_counts, image_counts, empty_images = collect_split_stats("train")
    print_distribution("ORIGINAL TRAIN DISTRIBUTION", len(samples), empty_images, object_counts, image_counts)

    target_objects = {
        class_id: math.ceil(object_counts[class_id] * TARGET_OBJECT_MULTIPLIER[class_id])
        for class_id in range(len(CLASS_NAMES))
    }
    balanced_samples = list(samples)
    copy_counts = Counter(id(sample) for sample in balanced_samples)
    class_to_samples = defaultdict(list)
    for sample in samples:
        for class_id in sample["classes"]:
            class_to_samples[class_id].append(sample)

    balanced_object_counts = Counter(object_counts)
    cursor = Counter()

    while True:
        deficits = {
            class_id: target_objects[class_id] - balanced_object_counts[class_id]
            for class_id in range(len(CLASS_NAMES))
        }
        needed = [class_id for class_id, deficit in deficits.items() if deficit > 0]
        if not needed:
            break

        class_id = max(needed, key=lambda item: deficits[item] / max(target_objects[item], 1))
        candidates = class_to_samples[class_id]
        if not candidates:
            break

        selected = None
        for _ in range(len(candidates)):
            sample = candidates[cursor[class_id] % len(candidates)]
            cursor[class_id] += 1
            if copy_counts[id(sample)] < MAX_REPEAT:
                selected = sample
                break
        if selected is None:
            break

        balanced_samples.append(selected)
        copy_counts[id(selected)] += 1
        balanced_object_counts.update(selected["label_counts"])

    balanced_lines = [sample["image"].as_posix() for sample in balanced_samples]
    balanced_image_counts = Counter()
    balanced_empty_images = 0
    for sample in balanced_samples:
        if not sample["classes"]:
            balanced_empty_images += 1
        for class_id in sample["classes"]:
            balanced_image_counts[class_id] += 1

    train_list = DATASET_DIR / "train_balanced.txt"
    train_list.write_text("\n".join(balanced_lines) + "\n", encoding="utf-8")

    print_distribution(
        "BALANCED TRAIN EXPOSURE DISTRIBUTION",
        len(balanced_lines),
        balanced_empty_images,
        balanced_object_counts,
        balanced_image_counts,
    )
    print(f"\nBalanced train list: {train_list}")
    print(f"Target objects: {target_objects}")
    print(f"Target object multipliers: {TARGET_OBJECT_MULTIPLIER}")
    print(f"Max repeat per image: {MAX_REPEAT}")
    return train_list, balanced_object_counts, balanced_image_counts, balanced_empty_images


def write_full_data_yaml(train_list: Path) -> Path:
    yaml_path = DATASET_DIR / "data_full_balanced.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                f"path: {DATASET_DIR.as_posix()}",
                f"train: {train_list.as_posix()}",
                "val: valid/images",
                "test: test/images",
                "nc: 3",
                "names:",
                "  0: snow",
                "  1: water_accumulation",
                "  2: flood",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return yaml_path


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
        precision = per_class_precision[idx] if idx < len(per_class_precision) else float("nan")
        recall = per_class_recall[idx] if idx < len(per_class_recall) else float("nan")
        map50 = per_class_map50[idx] if idx < len(per_class_map50) else float("nan")
        map95 = per_class_map[idx] if idx < len(per_class_map) else float("nan")
        print(f"{idx:<3} {name:<21} {precision:<10.4f} {recall:<10.4f} {map50:<10.4f} {map95:<10.4f}")


def export_latest_results_summary(run_dir: Path) -> None:
    results_csv = run_dir / "results.csv"
    if not results_csv.exists():
        return
    with results_csv.open(newline="", encoding="utf-8") as file:
        rows = [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(file)]
    if not rows:
        return

    last = rows[-1]
    best = max(rows, key=lambda row: float(row.get("metrics/mAP50-95(B)", -1) or -1))
    print("\n" + "=" * 80)
    print("TRAINING CURVE SUMMARY")
    print("-" * 80)
    print(f"Last epoch: {last.get('epoch')}")
    print(
        "Last metrics: "
        f"P={float(last['metrics/precision(B)']):.4f}, "
        f"R={float(last['metrics/recall(B)']):.4f}, "
        f"mAP50={float(last['metrics/mAP50(B)']):.4f}, "
        f"mAP50-95={float(last['metrics/mAP50-95(B)']):.4f}"
    )
    print(f"Best mAP50-95 epoch: {best.get('epoch')}")
    print(
        "Best metrics: "
        f"P={float(best['metrics/precision(B)']):.4f}, "
        f"R={float(best['metrics/recall(B)']):.4f}, "
        f"mAP50={float(best['metrics/mAP50(B)']):.4f}, "
        f"mAP50-95={float(best['metrics/mAP50-95(B)']):.4f}"
    )


def latest_epoch(run_dir: Path) -> int:
    results_csv = run_dir / "results.csv"
    if not results_csv.exists():
        return 0
    with results_csv.open(newline="", encoding="utf-8") as file:
        rows = [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(file)]
    if not rows:
        return 0
    return int(float(rows[-1].get("epoch", 0)))


def main() -> None:
    resume_weights = RUN_DIR / "weights" / "last.pt"
    should_resume = RESUME_IF_AVAILABLE and resume_weights.exists()
    current_epoch = latest_epoch(RUN_DIR) if should_resume else 0
    initial_model_path = resume_weights if should_resume else (V2_BEST_MODEL_PATH if V2_BEST_MODEL_PATH.exists() else MODEL_PATH)
    if not initial_model_path.exists():
        raise FileNotFoundError(f"Model weights not found: {initial_model_path}")
    if not DATASET_DIR.exists():
        raise FileNotFoundError(f"Dataset directory not found: {DATASET_DIR}")

    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available. Please check your GPU/PyTorch environment.")
    print(f"GPU: {torch.cuda.get_device_name(DEVICE)}")
    print(f"Device setting: cuda:{DEVICE}")
    print(f"Batch: {BATCH}")
    print(f"Workers: {WORKERS}")
    print(f"Eval workers: {EVAL_WORKERS}")
    print(f"Cache: {CACHE}")
    print(f"Initial weights: {initial_model_path}")
    print(f"Resume enabled: {RESUME_IF_AVAILABLE}")
    print(f"Resume from checkpoint: {should_resume}")
    print(f"Current epoch: {current_epoch}")
    print(f"Target total epochs: {EPOCHS}")

    for split in ["valid", "test"]:
        samples, object_counts, image_counts, empty_images = collect_split_stats(split)
        print_distribution(f"{split.upper()} DISTRIBUTION", len(samples), empty_images, object_counts, image_counts)

    train_list, _, _, _ = build_balanced_train_list()
    data_yaml = write_full_data_yaml(train_list)
    print(f"\nTraining data yaml: {data_yaml}")

    if should_resume and current_epoch >= EPOCHS:
        print("\n" + "=" * 80)
        print(f"Training already reached {current_epoch} epochs. Skipping train and running evaluation.")
        run_dir = RUN_DIR
    else:
        model = YOLO(str(initial_model_path))
        if should_resume:
            train_results = model.train(resume=True, epochs=EPOCHS)
        else:
            train_results = model.train(
                data=str(data_yaml),
                epochs=EPOCHS,
                patience=PATIENCE,
                imgsz=IMGSZ,
                batch=BATCH,
                device=DEVICE,
                workers=WORKERS,
                project=str(RUNS_DIR),
                name=RUN_NAME,
                exist_ok=True,
                pretrained=True,
                val=True,
                plots=True,
                amp=True,
                cache=CACHE,
                cos_lr=True,
                lr0=0.003,
                lrf=0.01,
                warmup_epochs=5,
                mosaic=0.8,
                mixup=0.05,
                close_mosaic=15,
                deterministic=DETERMINISTIC,
                save_period=10,
            )
        run_dir = Path(getattr(train_results, "save_dir", RUNS_DIR / RUN_NAME))
    best_weights = run_dir / "weights" / "best.pt"
    last_weights = run_dir / "weights" / "last.pt"

    print("\n" + "=" * 80)
    print("TRAINING FINISHED")
    print(f"Run directory: {run_dir}")
    print(f"Best weights: {best_weights}")
    print(f"Last weights: {last_weights}")

    export_latest_results_summary(run_dir)

    eval_weights = best_weights if best_weights.exists() else last_weights
    eval_model = YOLO(str(eval_weights))
    print_metrics(
        "VALIDATION",
        eval_model.val(data=str(data_yaml), split="val", imgsz=IMGSZ, batch=BATCH, device=DEVICE, workers=EVAL_WORKERS),
    )
    print_metrics(
        "TEST",
        eval_model.val(data=str(data_yaml), split="test", imgsz=IMGSZ, batch=BATCH, device=DEVICE, workers=EVAL_WORKERS),
    )


if __name__ == "__main__":
    main()
