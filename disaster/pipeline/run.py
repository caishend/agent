"""
CLI 入口：单张图片 / 批量目录推理

示例:
    # 单张图片，保存可视化
    python -m pipeline.run --image path/to/img.jpg --save-vis

    # 批量目录，输出 JSON 结果
    python -m pipeline.run --image-dir path/to/folder --output-dir results/ --save-vis
"""

import argparse
import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path，使 `from pipeline.xxx` 能正常 import
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline import config
from pipeline.pipeline import DisasterPipeline

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def _serializable(obj):
    """把 result dict 中的 numpy 数组剔除（mask 不序列化），其余正常输出。"""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _serializable(v) for k, v in obj.items() if k != "mask"}
    if isinstance(obj, list):
        return [_serializable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return "<mask array>"
    return obj


def parse_args():
    parser = argparse.ArgumentParser(description="Disaster inspection pipeline")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--image",     type=Path, help="单张图片路径")
    src.add_argument("--image-dir", type=Path, help="图片目录（批量推理）")

    parser.add_argument("--output-dir",      type=Path,  default=config.DEFAULT_OUTPUT_DIR)
    parser.add_argument("--save-vis",        action="store_true", default=config.SAVE_VIS,
                        help="保存各专家的可视化图片")
    parser.add_argument("--device",          type=str,   default=config.DEVICE)
    parser.add_argument("--gate-threshold",  type=float, default=config.GATE_THRESHOLD)
    return parser.parse_args()


def run_one(pipe: DisasterPipeline, image_path: Path, output_dir: Path, save_vis: bool) -> dict:
    result = pipe.run(image_path)

    d = result["decisions"] if "decisions" in result else result["gate"]["decisions"]
    routed = [k for k, v in result["gate"]["decisions"].items() if v]
    print(f"  gate → {routed if routed else '(none)'}")

    if save_vis:
        saved = pipe.visualize(image_path, result, output_dir)
        for p in saved:
            print(f"  vis  → {p}")

    return result


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pipe = DisasterPipeline(device=args.device, gate_threshold=args.gate_threshold)

    if args.image:
        print(f"\n[run] {args.image}")
        result = run_one(pipe, args.image, args.output_dir, args.save_vis)
        out_json = args.output_dir / f"{args.image.stem}_result.json"
        out_json.write_text(
            json.dumps(_serializable(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  json → {out_json}")

    else:
        image_paths = sorted(
            p for p in args.image_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        )
        if not image_paths:
            print(f"[error] no images found in {args.image_dir}")
            sys.exit(1)

        print(f"\n[run] {len(image_paths)} images from {args.image_dir}")
        all_results = []
        for i, p in enumerate(image_paths, 1):
            print(f"[{i}/{len(image_paths)}] {p.name}")
            result = run_one(pipe, p, args.output_dir, args.save_vis)
            all_results.append(_serializable(result))

        summary_path = args.output_dir / "results.json"
        summary_path.write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[done] {len(all_results)} results → {summary_path}")


if __name__ == "__main__":
    main()
