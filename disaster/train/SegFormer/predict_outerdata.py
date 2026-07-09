import argparse
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
from tqdm import tqdm
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

from train_segformer import ID2LABEL, letterbox_image_and_mask


PALETTE = {
    0: (35, 35, 35),
    1: (50, 150, 255),
    2: (44, 168, 116),
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
GENERATED_SUFFIXES = ("_comparison", "_pred_mask", "_pred_overlay")


def find_checkpoint(run_dir):
    run_dir = Path(run_dir)
    for name in ("best", "last"):
        checkpoint = run_dir / name
        if (checkpoint / "config.json").exists():
            return checkpoint
    raise FileNotFoundError(f"No best/last checkpoint found in {run_dir}")


def list_images(input_dir):
    input_dir = Path(input_dir)
    images = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if any(path.stem.endswith(suffix) for suffix in GENERATED_SUFFIXES):
            continue
        images.append(path)
    if not images:
        raise RuntimeError(f"No input images found in {input_dir}")
    return images


def mask_to_color(mask):
    mask = np.asarray(mask, dtype=np.uint8)
    color = np.zeros((*mask.shape, 3), dtype=np.uint8)
    for class_id, rgb in PALETTE.items():
        color[mask == class_id] = rgb
    return Image.fromarray(color, mode="RGB")


def overlay_mask(image, mask, alpha=0.45):
    return Image.blend(image.convert("RGB"), mask_to_color(mask), alpha)


def add_title(image, title, height=34):
    canvas = Image.new("RGB", (image.width, image.height + height), "white")
    canvas.paste(image, (0, height))
    draw = ImageDraw.Draw(canvas)
    draw.text((10, 9), title, fill=(20, 20, 20))
    return canvas


def make_comparison(image, pred, title):
    panels = [
        add_title(image, "original"),
        add_title(mask_to_color(pred), "prediction color map"),
        add_title(overlay_mask(image, pred), "prediction overlay"),
    ]
    panel_w, panel_h = panels[0].size
    margin = 12
    header_h = 42
    legend_h = 44
    canvas = Image.new(
        "RGB",
        (panel_w * 3 + margin * 4, header_h + panel_h + margin * 2 + legend_h),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 12), title, fill=(20, 20, 20))

    for idx, panel in enumerate(panels):
        x = margin + idx * (panel_w + margin)
        y = header_h + margin
        canvas.paste(panel, (x, y))

    legend_y = header_h + panel_h + margin * 2 + 8
    x = margin
    for class_id, label in ID2LABEL.items():
        rgb = PALETTE[class_id]
        draw.rectangle([x, legend_y, x + 18, legend_y + 18], fill=rgb)
        draw.text((x + 24, legend_y + 2), label, fill=(20, 20, 20))
        x += 180
    return canvas


def letterbox_image(image, image_size):
    original_w, original_h = image.size
    scale = min(image_size / original_w, image_size / original_h)
    new_w = max(1, int(round(original_w * scale)))
    new_h = max(1, int(round(original_h * scale)))
    pad_left = (image_size - new_w) // 2
    pad_top = (image_size - new_h) // 2
    canvas, _ = letterbox_image_and_mask(image, None, image_size)
    return canvas, (pad_left, pad_top, new_w, new_h)


@torch.no_grad()
def predict_image(model, processor, image_path, image_size, device):
    original = Image.open(image_path).convert("RGB")
    letterboxed, (pad_left, pad_top, new_w, new_h) = letterbox_image(original, image_size)
    pixel_values = processor(images=letterboxed, return_tensors="pt")["pixel_values"].to(device)
    logits = model(pixel_values=pixel_values).logits
    logits = F.interpolate(logits, size=(image_size, image_size), mode="bilinear", align_corners=False)
    pred = logits.argmax(dim=1).squeeze(0).cpu().numpy().astype(np.uint8)
    pred = pred[pad_top:pad_top + new_h, pad_left:pad_left + new_w]
    pred_image = Image.fromarray(pred, mode="L").resize(original.size, Image.NEAREST)
    pred = np.asarray(pred_image, dtype=np.uint8)
    return original, pred


def class_pixel_summary(pred):
    total = pred.size
    summary = {}
    for class_id, label in ID2LABEL.items():
        pixels = int((pred == class_id).sum())
        summary[label] = {
            "pixels": pixels,
            "ratio": float(pixels / total) if total else 0.0,
        }
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="Predict outerdata images with the trained SegFormer model.")
    parser.add_argument("--input-dir", type=Path, default=Path(r"D:\zhinengruanjianlingyu2\outerdata"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--run-dir", type=Path, default=Path(r"D:\zhinengruanjianlingyu2\runs\segformer_mit_b3"))
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--image-size", type=int, default=512)
    parser.add_argument("--offline", action="store_true", default=True)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--save-mask", action="store_true", help="Also save predicted class-id masks.")
    parser.add_argument("--save-overlay", action="store_true", help="Also save prediction overlays.")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    output_dir = args.output_dir or args.input_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.checkpoint or find_checkpoint(args.run_dir)

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    print(f"device: {device}")
    if device.type == "cuda":
        print(f"gpu: {torch.cuda.get_device_name(0)}")
    print(f"checkpoint: {checkpoint}")

    processor = SegformerImageProcessor.from_pretrained(
        checkpoint,
        do_resize=False,
        do_reduce_labels=False,
        local_files_only=args.offline,
    )
    model = SegformerForSemanticSegmentation.from_pretrained(
        checkpoint,
        local_files_only=args.offline,
    ).to(device)
    model.eval()

    images = list_images(args.input_dir)
    rows = []
    for image_path in tqdm(images, desc="predict"):
        image, pred = predict_image(model, processor, image_path, args.image_size, device)
        summary = class_pixel_summary(pred)
        title = (
            f"{image_path.name} | pipe={summary['pipe']['ratio']:.2%} "
            f"construction_area={summary['construction_area']['ratio']:.2%}"
        )
        comparison = make_comparison(image, pred, title)
        comparison_path = output_dir / f"{image_path.stem}_comparison.png"
        comparison.save(comparison_path)

        if args.save_mask:
            Image.fromarray(pred, mode="L").save(output_dir / f"{image_path.stem}_pred_mask.png")
        if args.save_overlay:
            overlay_mask(image, pred).save(output_dir / f"{image_path.stem}_pred_overlay.png")

        rows.append(
            {
                "image": image_path.name,
                "comparison": comparison_path.name,
                "summary": summary,
            }
        )

    summary_path = output_dir / "outerdata_predictions.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "checkpoint": str(checkpoint),
                "image_size": args.image_size,
                "images": rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"saved {len(rows)} comparison images to {output_dir}")
    print(f"saved summary: {summary_path}")


if __name__ == "__main__":
    main()
