from pathlib import Path

import cv2
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

IMGSZ = 768
BATCH = 4
DEVICE = 0
WORKERS = 0
CONF = 0.25
IOU = 0.70
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

GT_COLOR = (0, 0, 255)
PRED_COLOR = (0, 180, 0)


def find_best_weights() -> tuple[Path, Path]:
    for run_dir in RUN_DIR_CANDIDATES:
        best = run_dir / "weights" / "best.pt"
        last = run_dir / "weights" / "last.pt"
        if best.exists():
            return best, run_dir
        if last.exists():
            return last, run_dir
    searched = "\n".join(str(path / "weights") for path in RUN_DIR_CANDIDATES)
    raise FileNotFoundError(f"No weights found. Searched:\n{searched}")


def print_metrics(title: str, metrics) -> None:
    box = metrics.box
    print("\n" + "=" * 80)
    print(title)
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


def read_yolo_labels(label_path: Path, width: int, height: int) -> list[dict]:
    labels = []
    if not label_path.exists():
        return labels
    for line in label_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        class_id = int(float(parts[0]))
        x, y, w, h = map(float, parts[1:5])
        x1 = int((x - w / 2) * width)
        y1 = int((y - h / 2) * height)
        x2 = int((x + w / 2) * width)
        y2 = int((y + h / 2) * height)
        labels.append(
            {
                "class_id": class_id,
                "box": [max(0, x1), max(0, y1), min(width - 1, x2), min(height - 1, y2)],
            }
        )
    return labels


def draw_label(image, box, text: str, color: tuple[int, int, int], thickness: int) -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)
    text_y = max(18, y1 - 6)
    cv2.putText(image, text, (x1, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)


def save_gt_pred_images(model: YOLO, out_dir: Path) -> None:
    image_dir = ROOT / "merged_yolo_8_1_1" / "test" / "images"
    label_dir = ROOT / "merged_yolo_8_1_1" / "test" / "labels"
    image_paths = sorted(path for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTS)

    out_dir.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 80)
    print(f"Saving GT + prediction annotated images to: {out_dir}")

    for index, image_path in enumerate(image_paths, start=1):
        if index == 1 or index % 50 == 0 or index == len(image_paths):
            print(f"Annotating {index}/{len(image_paths)}")

        image = cv2.imread(str(image_path))
        if image is None:
            continue
        height, width = image.shape[:2]

        labels = read_yolo_labels(label_dir / f"{image_path.stem}.txt", width, height)
        with torch.inference_mode():
            result = model.predict(
                source=str(image_path),
                imgsz=IMGSZ,
                conf=CONF,
                iou=IOU,
                device=DEVICE,
                batch=1,
                verbose=False,
            )[0]

        for label in labels:
            class_name = CLASS_NAMES[label["class_id"]]
            draw_label(image, label["box"], f"GT {class_name}", GT_COLOR, 2)

        if result.boxes is not None:
            boxes = result.boxes.xyxy.detach().cpu().tolist()
            classes = result.boxes.cls.detach().cpu().tolist()
            confs = result.boxes.conf.detach().cpu().tolist()
            for box, class_id, conf in zip(boxes, classes, confs):
                class_id = int(class_id)
                class_name = CLASS_NAMES[class_id] if class_id < len(CLASS_NAMES) else str(class_id)
                int_box = [int(value) for value in box]
                draw_label(image, int_box, f"P {class_name} {conf:.2f}", PRED_COLOR, 2)

        cv2.imwrite(str(out_dir / f"{image_path.stem}_gt_pred.jpg"), image)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def main() -> None:
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(DEVICE)}")

    weights, run_dir = find_best_weights()
    print(f"Run dir: {run_dir}")
    print(f"Weights: {weights}")
    print(f"Data yaml: {DATA_YAML}")

    model = YOLO(str(weights))

    metrics = model.val(
        data=str(DATA_YAML),
        split="test",
        imgsz=IMGSZ,
        batch=BATCH,
        device=DEVICE,
        workers=WORKERS,
        conf=CONF,
        iou=IOU,
        plots=True,
        save_json=False,
    )
    print_metrics("TEST SET METRICS", metrics)

    predict_dir = ROOT / "runs_detect" / "best_test_predictions"
    model.predict(
        source=str(ROOT / "merged_yolo_8_1_1" / "test" / "images"),
        imgsz=IMGSZ,
        conf=CONF,
        iou=IOU,
        device=DEVICE,
        save=True,
        project=str(predict_dir.parent),
        name=predict_dir.name,
        exist_ok=True,
        verbose=False,
    )
    gt_pred_dir = ROOT / "runs_detect" / "best_test_gt_pred"
    save_gt_pred_images(model, gt_pred_dir)

    print("\n" + "=" * 80)
    print(f"Prediction images saved to: {predict_dir}")
    print(f"GT + prediction images saved to: {gt_pred_dir}")


if __name__ == "__main__":
    main()
