import argparse
import csv
import json
import os
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

from train_segformer import ID2LABEL, collate_fn, letterbox_image_and_mask, metrics_from_confusion_matrix


PALETTE = {
    0: (35, 35, 35),        # background
    1: (50, 150, 255),     # pipe
    2: (44, 168, 116),     # construction_area
}
ERROR_PALETTE = {
    0: (35, 35, 35),       # correct background
    1: (50, 150, 255),     # correct pipe
    2: (120, 220, 120),    # correct construction_area
    3: (255, 70, 70),      # any wrong prediction
}


class TestSegDataset(Dataset):
    def __init__(self, data_dir, split, processor, image_size):
        self.data_dir = Path(data_dir)
        self.processor = processor
        self.image_size = image_size
        self.image_dir = self.data_dir / split / "images"
        self.mask_dir = self.data_dir / split / "masks"
        self.samples = []

        for image_path in sorted(self.image_dir.glob("*.jpg")):
            mask_path = self.mask_dir / f"{image_path.stem}_mask.png"
            if mask_path.exists():
                self.samples.append((image_path, mask_path))

        if not self.samples:
            raise RuntimeError(f"No samples found in {self.image_dir}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        image_path, mask_path = self.samples[index]
        image = Image.open(image_path).convert("RGB")
        mask = Image.open(mask_path).convert("L")
        image, mask = letterbox_image_and_mask(image, mask, self.image_size)
        pixel_values = self.processor(images=image, return_tensors="pt")["pixel_values"].squeeze(0)
        labels = torch.from_numpy(np.array(mask, dtype=np.int64))
        return {"pixel_values": pixel_values, "labels": labels}


def update_confusion_matrix_from_preds(confusion_matrix, preds, labels, num_classes):
    labels = labels.reshape(-1)
    preds = preds.reshape(-1)
    valid = (labels >= 0) & (labels < num_classes)
    labels = labels[valid]
    preds = preds[valid]
    indices = labels * num_classes + preds
    bins = torch.bincount(indices, minlength=num_classes * num_classes)
    confusion_matrix += bins.reshape(num_classes, num_classes).cpu()


def flatten_metrics(metrics):
    row = {
        "loss": metrics["loss"],
        "pixel_acc": metrics["pixel_acc"],
        "mean_accuracy": metrics["mean_accuracy"],
        "mean_precision": metrics["mean_precision"],
        "mean_recall": metrics["mean_recall"],
        "miou": metrics["miou"],
        "foreground_miou": metrics["foreground_miou"],
        "foreground_precision": metrics["foreground_precision"],
        "foreground_recall": metrics["foreground_recall"],
    }
    for class_name, class_metrics in metrics["classes"].items():
        prefix = class_name.replace(" ", "_")
        row[f"{prefix}_precision"] = class_metrics["precision"]
        row[f"{prefix}_recall"] = class_metrics["recall"]
        row[f"{prefix}_iou"] = class_metrics["iou"]
        row[f"{prefix}_support_pixels"] = class_metrics["support_pixels"]
        row[f"{prefix}_pred_pixels"] = class_metrics["pred_pixels"]
    return row


def write_single_row_csv(path, row):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def write_per_class_csv(path, metrics):
    fieldnames = ["class_id", "class_name", "precision", "recall", "iou", "support_pixels", "pred_pixels"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for class_id, class_name in ID2LABEL.items():
            row = {"class_id": class_id, "class_name": class_name}
            row.update(metrics["classes"][class_name])
            writer.writerow(row)


def write_confusion_matrix_csv(path, matrix):
    labels = [ID2LABEL[i] for i in range(len(ID2LABEL))]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["gt\\pred"] + labels)
        for i, row in enumerate(matrix):
            writer.writerow([labels[i]] + row)


def mask_to_color(mask):
    mask = np.asarray(mask, dtype=np.uint8)
    color = np.zeros((*mask.shape, 3), dtype=np.uint8)
    for class_id, rgb in PALETTE.items():
        color[mask == class_id] = rgb
    return Image.fromarray(color, mode="RGB")


def overlay_mask(image, mask, alpha=0.45):
    color = mask_to_color(mask)
    return Image.blend(image.convert("RGB"), color, alpha)


def error_to_color(gt, pred):
    gt = np.asarray(gt, dtype=np.uint8)
    pred = np.asarray(pred, dtype=np.uint8)
    error = np.zeros_like(gt, dtype=np.uint8)
    error[(gt == pred) & (gt == 1)] = 1
    error[(gt == pred) & (gt == 2)] = 2
    error[gt != pred] = 3

    color = np.zeros((*gt.shape, 3), dtype=np.uint8)
    for error_id, rgb in ERROR_PALETTE.items():
        color[error == error_id] = rgb
    return Image.fromarray(color, mode="RGB")


def add_title(image, title, height=34):
    canvas = Image.new("RGB", (image.width, image.height + height), "white")
    canvas.paste(image, (0, height))
    draw = ImageDraw.Draw(canvas)
    draw.text((10, 9), title, fill=(20, 20, 20))
    return canvas


def make_visualization(image, gt, pred, title):
    panels = [
        add_title(image, "original"),
        add_title(mask_to_color(gt), "gt color map"),
        add_title(mask_to_color(pred), "pred color map"),
        add_title(overlay_mask(image, gt), "gt overlay"),
        add_title(overlay_mask(image, pred), "pred overlay"),
        add_title(error_to_color(gt, pred), "error map"),
    ]
    panel_w, panel_h = panels[0].size
    margin = 12
    header_h = 42
    legend_h = 44
    canvas = Image.new(
        "RGB",
        (panel_w * 3 + margin * 4, header_h + panel_h * 2 + margin * 3 + legend_h),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 12), title, fill=(20, 20, 20))

    for idx, panel in enumerate(panels):
        row = idx // 3
        col = idx % 3
        x = margin + col * (panel_w + margin)
        y = header_h + margin + row * (panel_h + margin)
        canvas.paste(panel, (x, y))

    legend_y = header_h + panel_h * 2 + margin * 3 + 8
    legend_items = [
        ("background", PALETTE[0]),
        ("pipe", PALETTE[1]),
        ("construction_area", PALETTE[2]),
        ("wrong prediction", ERROR_PALETTE[3]),
    ]
    x = margin
    for label, rgb in legend_items:
        draw.rectangle([x, legend_y, x + 18, legend_y + 18], fill=rgb)
        draw.text((x + 24, legend_y + 2), label, fill=(20, 20, 20))
        x += 150
    return canvas


@torch.no_grad()
def predict_one(model, processor, image_path, mask_path, image_size, device):
    image = Image.open(image_path).convert("RGB")
    gt = Image.open(mask_path).convert("L")
    image, gt = letterbox_image_and_mask(image, gt, image_size)
    pixel_values = processor(images=image, return_tensors="pt")["pixel_values"].to(device)
    logits = model(pixel_values=pixel_values).logits
    logits = F.interpolate(logits, size=(image_size, image_size), mode="bilinear", align_corners=False)
    pred = logits.argmax(dim=1).squeeze(0).cpu().numpy().astype(np.uint8)
    return image, np.asarray(gt, dtype=np.uint8), pred


@torch.no_grad()
def evaluate(model, loader, dataset, device):
    model.eval()
    losses = []
    confusion_matrix = torch.zeros((len(ID2LABEL), len(ID2LABEL)), dtype=torch.int64)
    per_image_rows = []
    sample_offset = 0

    for batch in tqdm(loader, desc="test"):
        pixel_values = batch["pixel_values"].to(device, non_blocking=True)
        labels = batch["labels"].to(device, non_blocking=True)
        outputs = model(pixel_values=pixel_values, labels=labels)
        logits = F.interpolate(outputs.logits, size=labels.shape[-2:], mode="bilinear", align_corners=False)
        preds = logits.argmax(dim=1)
        update_confusion_matrix_from_preds(confusion_matrix, preds, labels, len(ID2LABEL))
        losses.append(outputs.loss.item())

        for i in range(labels.shape[0]):
            image_path, mask_path = dataset.samples[sample_offset + i]
            image_cm = torch.zeros((len(ID2LABEL), len(ID2LABEL)), dtype=torch.int64)
            update_confusion_matrix_from_preds(image_cm, preds[i], labels[i], len(ID2LABEL))
            image_metrics = metrics_from_confusion_matrix(image_cm)
            row = flatten_metrics({"loss": outputs.loss.item(), **image_metrics})
            row["image"] = image_path.name
            row["mask"] = mask_path.name
            per_image_rows.append(row)
        sample_offset += labels.shape[0]

    metrics = metrics_from_confusion_matrix(confusion_matrix)
    metrics["loss"] = float(np.mean(losses)) if losses else 0.0
    return metrics, per_image_rows


def save_per_image_csv(path, rows):
    if not rows:
        return
    fieldnames = ["image", "mask"] + [k for k in rows[0].keys() if k not in {"image", "mask"}]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def foreground_classes_in_mask(mask_path):
    mask = np.asarray(Image.open(mask_path).convert("L"), dtype=np.uint8)
    classes = set(int(class_id) for class_id in np.unique(mask))
    return sorted(class_id for class_id in classes if class_id != 0 and class_id in ID2LABEL)


def select_single_label_visualizations(dataset, rows, max_visualizations):
    by_class = {1: [], 2: []}
    for index, (_, mask_path) in enumerate(dataset.samples):
        foreground_classes = foreground_classes_in_mask(mask_path)
        if len(foreground_classes) == 1 and foreground_classes[0] in by_class:
            by_class[foreground_classes[0]].append(index)

    if max_visualizations <= 0:
        per_class_limit = min(len(by_class[1]), len(by_class[2]))
    else:
        per_class_limit = min(len(by_class[1]), len(by_class[2]), max_visualizations // 2)

    selected = by_class[1][:per_class_limit] + by_class[2][:per_class_limit]
    if max_visualizations > 0 and len(selected) < max_visualizations:
        remaining_slots = max_visualizations - len(selected)
        extras = []
        extras.extend(by_class[1][per_class_limit:])
        extras.extend(by_class[2][per_class_limit:])
        selected.extend(extras[:remaining_slots])

    selected = sorted(set(selected))
    class_counts = {ID2LABEL[class_id]: 0 for class_id in by_class}
    for index in selected:
        foreground_classes = foreground_classes_in_mask(dataset.samples[index][1])
        if len(foreground_classes) == 1 and foreground_classes[0] in by_class:
            class_counts[ID2LABEL[foreground_classes[0]]] += 1
    return selected, class_counts, {ID2LABEL[class_id]: len(indices) for class_id, indices in by_class.items()}


def save_visualizations(model, processor, dataset, rows, args, device):
    visual_dir = args.output_dir / "visualizations"
    visual_dir.mkdir(parents=True, exist_ok=True)

    selected, selected_counts, available_counts = select_single_label_visualizations(
        dataset, rows, args.max_visualizations
    )
    selection_info = {
        "rule": "GT mask contains exactly one foreground class: pipe or construction_area",
        "max_visualizations": args.max_visualizations,
        "available_single_label_images": available_counts,
        "selected_single_label_images": selected_counts,
        "selected_total": len(selected),
        "selected_files": [dataset.samples[index][0].name for index in selected],
    }
    with (args.output_dir / "visualization_selection.json").open("w", encoding="utf-8") as f:
        json.dump(selection_info, f, ensure_ascii=False, indent=2)
    print(
        "visualization selection: "
        f"pipe={selected_counts['pipe']} construction_area={selected_counts['construction_area']} "
        f"(available pipe={available_counts['pipe']}, "
        f"construction_area={available_counts['construction_area']})"
    )

    for index in tqdm(selected, desc="visualize"):
        image_path, mask_path = dataset.samples[index]
        foreground_classes = foreground_classes_in_mask(mask_path)
        gt_label = ID2LABEL[foreground_classes[0]] if len(foreground_classes) == 1 else "mixed"
        image, gt, pred = predict_one(model, processor, image_path, mask_path, args.image_size, device)
        row = rows[index]
        title = (
            f"{image_path.name} | gt={gt_label} | fg_mIoU={row['foreground_miou']:.4f} "
            f"pipe_iou={row['pipe_iou']:.4f} construction_iou={row['construction_area_iou']:.4f}"
        )
        canvas = make_visualization(image, gt, pred, title)
        canvas.save(visual_dir / f"{gt_label}_{image_path.stem}_comparison.png")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(r"D:\zhinengruanjianlingyu2\mergedata"))
    parser.add_argument("--checkpoint", type=Path, default=Path(r"D:\zhinengruanjianlingyu2\runs\segformer_mit_b3_letterbox_768\best"))
    parser.add_argument("--output-dir", type=Path, default=Path(r"D:\zhinengruanjianlingyu2\runs\segformer_mit_b3_letterbox_768\test_best"))
    parser.add_argument("--split", default="test")
    parser.add_argument("--image-size", type=int, default=768)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--max-visualizations", type=int, default=50)
    parser.add_argument("--offline", action="store_true", default=True)
    parser.add_argument("--cpu", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    args.output_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    print(f"device: {device}")
    if device.type == "cuda":
        print(f"gpu: {torch.cuda.get_device_name(0)}")

    processor = SegformerImageProcessor.from_pretrained(
        args.checkpoint,
        do_resize=False,
        do_reduce_labels=False,
        local_files_only=args.offline,
    )
    model = SegformerForSemanticSegmentation.from_pretrained(
        args.checkpoint,
        local_files_only=args.offline,
    ).to(device)

    dataset = TestSegDataset(args.data_dir, args.split, processor, args.image_size)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
        collate_fn=collate_fn,
    )
    print(f"{args.split} samples: {len(dataset)}")

    metrics, per_image_rows = evaluate(model, loader, dataset, device)
    summary_row = flatten_metrics(metrics)
    summary_row["split"] = args.split
    summary_row["samples"] = len(dataset)
    summary_row["checkpoint"] = str(args.checkpoint)

    write_single_row_csv(args.output_dir / "test_metrics.csv", summary_row)
    write_per_class_csv(args.output_dir / "test_per_class_metrics.csv", metrics)
    write_confusion_matrix_csv(args.output_dir / "test_confusion_matrix.csv", metrics["confusion_matrix"])
    save_per_image_csv(args.output_dir / "test_per_image_metrics.csv", per_image_rows)
    with (args.output_dir / "test_metrics.json").open("w", encoding="utf-8") as f:
        json.dump({"summary": summary_row, "classes": metrics["classes"], "confusion_matrix": metrics["confusion_matrix"]}, f, ensure_ascii=False, indent=2)

    save_visualizations(model, processor, dataset, per_image_rows, args, device)

    print("test summary:")
    for key in ["loss", "pixel_acc", "mean_precision", "mean_recall", "miou", "foreground_miou"]:
        print(f"  {key}: {summary_row[key]:.6f}")
    for class_name, class_metrics in metrics["classes"].items():
        print(
            f"  {class_name}: precision={class_metrics['precision']:.6f} "
            f"recall={class_metrics['recall']:.6f} iou={class_metrics['iou']:.6f}"
        )
    print(f"saved outputs: {args.output_dir}")


if __name__ == "__main__":
    main()
