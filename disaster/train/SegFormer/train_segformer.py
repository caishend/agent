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
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor


ID2LABEL = {
    0: "background",
    1: "pipe",
    2: "construction_area",
}
LABEL2ID = {name: idx for idx, name in ID2LABEL.items()}


def letterbox_image_and_mask(image, mask, image_size, fill=(0, 0, 0), mask_fill=0):
    """Resize with unchanged aspect ratio, then pad to a square canvas."""
    original_w, original_h = image.size
    scale = min(image_size / original_w, image_size / original_h)
    new_w = max(1, int(round(original_w * scale)))
    new_h = max(1, int(round(original_h * scale)))
    pad_left = (image_size - new_w) // 2
    pad_top = (image_size - new_h) // 2

    resized_image = image.resize((new_w, new_h), Image.BILINEAR)
    canvas_image = Image.new("RGB", (image_size, image_size), fill)
    canvas_image.paste(resized_image, (pad_left, pad_top))

    if mask is None:
        return canvas_image, None

    resized_mask = mask.resize((new_w, new_h), Image.NEAREST)
    canvas_mask = Image.new("L", (image_size, image_size), mask_fill)
    canvas_mask.paste(resized_mask, (pad_left, pad_top))
    return canvas_image, canvas_mask


class MergedSegDataset(Dataset):
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


def collate_fn(batch):
    return {
        "pixel_values": torch.stack([item["pixel_values"] for item in batch]),
        "labels": torch.stack([item["labels"] for item in batch]),
    }


def update_confusion_matrix(confusion_matrix, logits, labels, num_classes):
    logits = F.interpolate(logits, size=labels.shape[-2:], mode="bilinear", align_corners=False)
    preds = logits.argmax(dim=1)

    labels = labels.reshape(-1)
    preds = preds.reshape(-1)
    valid = (labels >= 0) & (labels < num_classes)
    labels = labels[valid]
    preds = preds[valid]

    indices = labels * num_classes + preds
    bins = torch.bincount(indices, minlength=num_classes * num_classes)
    confusion_matrix += bins.reshape(num_classes, num_classes).cpu()


def metrics_from_confusion_matrix(confusion_matrix):
    matrix = confusion_matrix.numpy().astype(np.float64)
    tp = np.diag(matrix)
    label_total = matrix.sum(axis=1)
    pred_total = matrix.sum(axis=0)
    total = matrix.sum()

    precision = np.divide(tp, pred_total, out=np.zeros_like(tp), where=pred_total > 0)
    recall = np.divide(tp, label_total, out=np.zeros_like(tp), where=label_total > 0)
    iou_den = label_total + pred_total - tp
    iou = np.divide(tp, iou_den, out=np.zeros_like(tp), where=iou_den > 0)

    valid_classes = label_total > 0
    foreground = np.array([class_id != 0 for class_id in range(len(ID2LABEL))]) & valid_classes

    class_metrics = {}
    for class_id, class_name in ID2LABEL.items():
        class_metrics[class_name] = {
            "precision": float(precision[class_id]),
            "recall": float(recall[class_id]),
            "iou": float(iou[class_id]),
            "support_pixels": int(label_total[class_id]),
            "pred_pixels": int(pred_total[class_id]),
        }

    return {
        "pixel_acc": float(tp.sum() / total) if total else 0.0,
        "mean_accuracy": float(np.mean(recall[valid_classes])) if valid_classes.any() else 0.0,
        "mean_precision": float(np.mean(precision[valid_classes])) if valid_classes.any() else 0.0,
        "mean_recall": float(np.mean(recall[valid_classes])) if valid_classes.any() else 0.0,
        "miou": float(np.mean(iou[valid_classes])) if valid_classes.any() else 0.0,
        "foreground_miou": float(np.mean(iou[foreground])) if foreground.any() else 0.0,
        "foreground_precision": float(np.mean(precision[foreground])) if foreground.any() else 0.0,
        "foreground_recall": float(np.mean(recall[foreground])) if foreground.any() else 0.0,
        "classes": class_metrics,
        "confusion_matrix": matrix.astype(int).tolist(),
    }


@torch.no_grad()
def validate(model, loader, device):
    model.eval()
    losses = []
    confusion_matrix = torch.zeros((len(ID2LABEL), len(ID2LABEL)), dtype=torch.int64)

    for batch in tqdm(loader, desc="valid", leave=False):
        pixel_values = batch["pixel_values"].to(device, non_blocking=True)
        labels = batch["labels"].to(device, non_blocking=True)
        outputs = model(pixel_values=pixel_values, labels=labels)
        update_confusion_matrix(confusion_matrix, outputs.logits, labels, len(ID2LABEL))
        losses.append(outputs.loss.item())

    metrics = metrics_from_confusion_matrix(confusion_matrix)
    metrics["loss"] = float(np.mean(losses))
    return metrics


def flatten_epoch_metrics(epoch, global_step, train_loss, valid_metrics):
    row = {
        "epoch": epoch,
        "global_step": global_step,
        "train_loss": train_loss,
        "valid_loss": valid_metrics["loss"],
        "pixel_acc": valid_metrics["pixel_acc"],
        "mean_accuracy": valid_metrics["mean_accuracy"],
        "mean_precision": valid_metrics["mean_precision"],
        "mean_recall": valid_metrics["mean_recall"],
        "miou": valid_metrics["miou"],
        "foreground_miou": valid_metrics["foreground_miou"],
        "foreground_precision": valid_metrics["foreground_precision"],
        "foreground_recall": valid_metrics["foreground_recall"],
    }

    for class_name, class_metrics in valid_metrics["classes"].items():
        prefix = class_name.replace(" ", "_")
        row[f"{prefix}_precision"] = class_metrics["precision"]
        row[f"{prefix}_recall"] = class_metrics["recall"]
        row[f"{prefix}_iou"] = class_metrics["iou"]
        row[f"{prefix}_support_pixels"] = class_metrics["support_pixels"]
        row[f"{prefix}_pred_pixels"] = class_metrics["pred_pixels"]

    return row


def print_epoch_metrics(epoch, row, valid_metrics):
    print(
        f"epoch {epoch}: "
        f"train_loss={row['train_loss']:.4f} "
        f"valid_loss={row['valid_loss']:.4f} "
        f"pixel_acc={row['pixel_acc']:.4f} "
        f"mean_precision={row['mean_precision']:.4f} "
        f"mean_recall={row['mean_recall']:.4f} "
        f"miou={row['miou']:.4f} "
        f"foreground_miou={row['foreground_miou']:.4f}"
    )
    print("class metrics:")
    for class_name, class_metrics in valid_metrics["classes"].items():
        print(
            f"  {class_name}: "
            f"precision={class_metrics['precision']:.4f} "
            f"recall={class_metrics['recall']:.4f} "
            f"iou={class_metrics['iou']:.4f} "
            f"support_pixels={class_metrics['support_pixels']} "
            f"pred_pixels={class_metrics['pred_pixels']}"
        )


def save_epoch_metrics(csv_path, jsonl_path, row, valid_metrics):
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    record = dict(row)
    record["classes"] = valid_metrics["classes"]
    record["confusion_matrix"] = valid_metrics["confusion_matrix"]
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_loaders(args, processor, device, image_size, batch_size):
    train_set = MergedSegDataset(args.data_dir, "train", processor, image_size)
    valid_set = MergedSegDataset(args.data_dir, "valid", processor, image_size)

    train_loader = DataLoader(
        train_set,
        batch_size=batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
        collate_fn=collate_fn,
    )
    valid_loader = DataLoader(
        valid_set,
        batch_size=batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
        collate_fn=collate_fn,
    )
    return train_loader, valid_loader, len(train_set), len(valid_set)


def gpu_memory_summary(device):
    if device.type != "cuda":
        return {}
    return {
        "mem_alloc_gb": torch.cuda.memory_allocated(device) / 1024**3,
        "mem_reserved_gb": torch.cuda.memory_reserved(device) / 1024**3,
        "max_mem_alloc_gb": torch.cuda.max_memory_allocated(device) / 1024**3,
        "max_mem_reserved_gb": torch.cuda.max_memory_reserved(device) / 1024**3,
    }


def resolve_resume_dir(args, output_dir):
    if not args.resume:
        return None
    if args.resume_from:
        resume_dir = Path(args.resume_from)
    else:
        resume_dir = output_dir / "last"
    if not resume_dir.exists():
        raise FileNotFoundError(f"Resume checkpoint not found: {resume_dir}")
    return resume_dir


def save_training_state(last_dir, epoch, global_step, best_foreground_miou, optimizer, scaler, args):
    state = {
        "epoch": epoch,
        "global_step": global_step,
        "best_foreground_miou": best_foreground_miou,
        "optimizer": optimizer.state_dict(),
        "scaler": scaler.state_dict(),
        "args": vars(args),
    }
    torch.save(state, last_dir / "training_state.pt")


def load_training_state(resume_dir, optimizer, scaler, device):
    state_path = resume_dir / "training_state.pt"
    if not state_path.exists():
        print(f"warning: no training_state.pt found in {resume_dir}; model weights will resume without optimizer state")
        return 0, 0, -1.0

    state = torch.load(state_path, map_location=device, weights_only=False)
    optimizer.load_state_dict(state["optimizer"])
    if state.get("scaler"):
        scaler.load_state_dict(state["scaler"])
    return (
        int(state.get("epoch", 0)),
        int(state.get("global_step", 0)),
        float(state.get("best_foreground_miou", -1.0)),
    )


def train(args):
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    print(f"device: {device}")
    if device.type == "cuda":
        print(f"gpu: {torch.cuda.get_device_name(0)}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    resume_dir = resolve_resume_dir(args, output_dir)
    model_source = str(resume_dir) if resume_dir else args.model_name

    processor = SegformerImageProcessor.from_pretrained(
        model_source,
        do_resize=False,
        do_reduce_labels=False,
        local_files_only=args.offline,
    )

    image_size = args.image_size
    batch_size = args.batch_size
    accumulation_steps = max(1, args.gradient_accumulation_steps)
    eval_every = max(1, args.eval_every)

    model = SegformerForSemanticSegmentation.from_pretrained(
        model_source,
        num_labels=len(ID2LABEL),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        ignore_mismatched_sizes=True,
        local_files_only=args.offline,
    ).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda" and args.amp)

    config_path = output_dir / "train_config.json"
    config = vars(args).copy()
    config["id2label"] = ID2LABEL
    config["label2id"] = LABEL2ID
    config["best_metric"] = "foreground_miou"
    config["effective_batch_size"] = batch_size * accumulation_steps
    config["device"] = str(device)
    if device.type == "cuda":
        config["gpu"] = torch.cuda.get_device_name(0)
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"saved config: {config_path}")

    metrics_csv = output_dir / "metrics.csv"
    metrics_jsonl = output_dir / "metrics.jsonl"
    if not resume_dir:
        for metrics_path in [metrics_csv, metrics_jsonl]:
            if metrics_path.exists():
                metrics_path.unlink()

    train_loader, valid_loader, train_count, valid_count = build_loaders(
        args, processor, device, image_size, batch_size
    )
    print(
        f"training: image_size={image_size} batch_size={batch_size} "
        f"gradient_accumulation_steps={accumulation_steps} "
        f"effective_batch_size={batch_size * accumulation_steps}"
    )
    print(f"train samples: {train_count}")
    print(f"valid samples: {valid_count}")

    best_foreground_miou = -1.0
    global_step = 0
    start_epoch = 1
    if resume_dir:
        completed_epoch, global_step, best_foreground_miou = load_training_state(
            resume_dir, optimizer, scaler, device
        )
        start_epoch = completed_epoch + 1
        print(
            f"resumed from {resume_dir}: "
            f"start_epoch={start_epoch}, global_step={global_step}, "
            f"best_foreground_miou={best_foreground_miou:.4f}"
        )

    for epoch in range(start_epoch, args.epochs + 1):
        model.train()
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        train_losses = []
        progress = tqdm(train_loader, desc=f"train {epoch}/{args.epochs}")
        optimizer.zero_grad(set_to_none=True)

        for step, batch in enumerate(progress, start=1):
            pixel_values = batch["pixel_values"].to(device, non_blocking=True)
            labels = batch["labels"].to(device, non_blocking=True)

            with torch.amp.autocast("cuda", enabled=device.type == "cuda" and args.amp):
                outputs = model(pixel_values=pixel_values, labels=labels)
                raw_loss = outputs.loss
                loss = raw_loss / accumulation_steps

            scaler.scale(loss).backward()

            should_step = step % accumulation_steps == 0 or step == len(train_loader)
            if should_step:
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
                global_step += 1

            train_losses.append(raw_loss.item())
            postfix = {
                "loss": f"{np.mean(train_losses):.4f}",
                "opt_step": global_step,
            }
            if device.type == "cuda":
                mem = gpu_memory_summary(device)
                postfix["mem"] = f"{mem['mem_alloc_gb']:.2f}G"
                postfix["reserved"] = f"{mem['mem_reserved_gb']:.2f}G"
            progress.set_postfix(**postfix)

            if args.max_steps and global_step >= args.max_steps:
                break

        train_loss = float(np.mean(train_losses))
        if device.type == "cuda":
            mem = gpu_memory_summary(device)
            print(
                f"gpu memory epoch {epoch}: "
                f"max_alloc={mem['max_mem_alloc_gb']:.2f}GB "
                f"max_reserved={mem['max_mem_reserved_gb']:.2f}GB "
                f"current_alloc={mem['mem_alloc_gb']:.2f}GB "
                f"current_reserved={mem['mem_reserved_gb']:.2f}GB"
            )
        should_eval = epoch % eval_every == 0 or epoch == args.epochs
        metrics = None
        if should_eval:
            metrics = validate(model, valid_loader, device)
            metrics_row = flatten_epoch_metrics(epoch, global_step, train_loss, metrics)
            metrics_row["image_size"] = image_size
            metrics_row["batch_size"] = batch_size
            metrics_row["gradient_accumulation_steps"] = accumulation_steps
            metrics_row["effective_batch_size"] = batch_size * accumulation_steps
            print_epoch_metrics(epoch, metrics_row, metrics)
            save_epoch_metrics(metrics_csv, metrics_jsonl, metrics_row, metrics)
            print(f"saved metrics: {metrics_csv}")
        else:
            print(
                f"epoch {epoch}: train_loss={train_loss:.4f} "
                f"(validation skipped; eval_every={eval_every})"
            )

        last_dir = output_dir / "last"
        model.save_pretrained(last_dir)
        processor.save_pretrained(last_dir)

        if metrics is not None and metrics["foreground_miou"] > best_foreground_miou:
            best_foreground_miou = metrics["foreground_miou"]
            best_dir = output_dir / "best"
            model.save_pretrained(best_dir)
            processor.save_pretrained(best_dir)
            print(f"saved best by foreground_miou={best_foreground_miou:.4f}: {best_dir}")

        save_training_state(
            last_dir,
            epoch,
            global_step,
            best_foreground_miou,
            optimizer,
            scaler,
            args,
        )

        if args.max_steps and global_step >= args.max_steps:
            break


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=r"D:\zhinengruanjianlingyu2\mergedata")
    parser.add_argument("--output-dir", default=r"D:\zhinengruanjianlingyu2\runs\segformer_mit_b3_letterbox_768")
    parser.add_argument("--model-name", default="nvidia/mit-b3")
    parser.add_argument("--image-size", type=int, default=768)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=2)
    parser.add_argument("--eval-every", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--lr", type=float, default=6e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--max-steps", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resume-from", default="")
    parser.add_argument("--offline", action="store_true", default=True)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--no-amp", dest="amp", action="store_false")
    parser.set_defaults(amp=True)
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())
