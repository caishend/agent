from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the disaster pipeline on one image with multiple gate thresholds.")
    parser.add_argument("image", type=Path, help="Image path to test.")
    parser.add_argument("--model-dir", type=Path, default=Path("disaster"), help="Disaster model project directory.")
    parser.add_argument("--device", default="auto", help="auto/cpu/cuda.")
    parser.add_argument("--thresholds", nargs="+", type=float, default=[0.5, 0.9], help="Gate thresholds to compare.")
    parser.add_argument("--output-dir", type=Path, default=Path("backend/data/remote_sensing/model_compare"))
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    image_path = _resolve(repo_root, args.image)
    model_dir = _resolve(repo_root, args.model_dir)
    output_dir = _resolve(repo_root, args.output_dir)

    if not image_path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")
    if not model_dir.exists():
        raise FileNotFoundError(f"model dir not found: {model_dir}")

    sys.path.insert(0, str(model_dir))
    from pipeline.pipeline import DisasterPipeline

    summaries: list[dict[str, Any]] = []
    pipeline = None
    for threshold in args.thresholds:
        if pipeline is None:
            pipeline = DisasterPipeline(device=args.device, gate_threshold=threshold)
        else:
            pipeline.gate_threshold = threshold

        result = pipeline.run(image_path)
        short_name = f"{image_path.stem[:40]}_{hashlib.md5(str(image_path).encode('utf-8')).hexdigest()[:8]}"
        visual_dir = output_dir / f"{short_name}_gate_{threshold:g}"
        visual_paths = pipeline.visualize(image_path, result, visual_dir)
        summary = _summarize(result, threshold, visual_paths)
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    output_dir.mkdir(parents=True, exist_ok=True)
    short_name = f"{image_path.stem[:40]}_{hashlib.md5(str(image_path).encode('utf-8')).hexdigest()[:8]}"
    summary_path = output_dir / f"{short_name}_compare.json"
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsummary_path={summary_path}")


def _resolve(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (repo_root / path).resolve()


def _summarize(result: dict[str, Any], threshold: float, visual_paths: list[Path]) -> dict[str, Any]:
    gate = result.get("gate") or {}
    snow = result.get("snow") or {}
    vitseg = result.get("vitseg") or {}
    segformer = result.get("segformer") or {}
    return {
        "threshold": threshold,
        "image_path": result.get("image_path"),
        "gate_probabilities": gate.get("probabilities"),
        "gate_decisions": gate.get("decisions"),
        "detections": snow.get("detections") or [],
        "vitseg_pixel_ratios": _non_background(vitseg.get("pixel_ratios")),
        "segformer_pixel_ratios": _non_background(segformer.get("pixel_ratios")),
        "visualizations": [str(path) for path in visual_paths],
    }


def _non_background(ratios: dict[str, Any] | None) -> dict[str, Any]:
    if not ratios:
        return {}
    return {key: value for key, value in ratios.items() if key != "background" and float(value or 0) > 0}


if __name__ == "__main__":
    main()
