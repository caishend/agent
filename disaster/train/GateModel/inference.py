"""
门控模型推理脚本
支持单张图片推理和批量推理，输出分发决策
"""

import os
import sys
import argparse
import json
from pathlib import Path
from typing import Union, List, Dict, Tuple

import torch
import numpy as np
from PIL import Image
from torchvision import transforms

from gating_model import GatingModel


# 专家路由配置
EXPERT_ROUTING = {
    0: {
        "name": "Group1 - OD专家 (目标检测)",
        "classes": ["snow", "water_accumulation", "flood"],
        "task": "object_detection",
    },
    1: {
        "name": "Group2 - Seg专家1 (语义分割)",
        "classes": ["debris_flow", "sinkhole", "crack", "landslide", "rockfall"],
        "task": "semantic_segmentation",
    },
    2: {
        "name": "Group3 - Seg专家2 (语义分割)",
        "classes": ["pipe", "construction_area"],
        "task": "semantic_segmentation",
    },
}

# 图像预处理（与训练时验证集一致）
INFERENCE_TRANSFORM = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])


def load_model(model_path: str, device: str = "auto") -> Tuple[GatingModel, dict]:
    """
    加载训练好的门控模型

    Args:
        model_path: 模型权重文件路径
        device: 设备
    Returns:
        model: 加载好的模型
        config: 模型配置
    """
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    checkpoint = torch.load(model_path, map_location=device, weights_only=False)

    # 获取阈值
    threshold = checkpoint.get("threshold", 0.5)
    config = checkpoint.get("config", {})

    # 创建模型并加载权重
    model = GatingModel(num_groups=3, pretrained=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model = model.to(device)
    model.eval()

    return model, {"threshold": threshold, "config": config, "device": device}


def predict_single(
    model: GatingModel,
    image_path: str,
    threshold: float = 0.5,
    device: str = "cuda",
) -> Dict:
    """
    对单张图片进行推理

    Args:
        model: 门控模型
        image_path: 图片路径
        threshold: 判定阈值
        device: 设备
    Returns:
        dict: 包含预测结果的字典
    """
    # 加载并预处理图片
    image = Image.open(image_path).convert("RGB")
    input_tensor = INFERENCE_TRANSFORM(image).unsqueeze(0).to(device)

    # 推理
    probs, predictions = model.predict(input_tensor, threshold=threshold)

    probs = probs.cpu().numpy()[0]  # (3,)
    predictions = predictions.cpu().numpy()[0]  # (3,)

    # 构建路由决策
    routing = []
    for i in range(3):
        routing.append({
            "group_id": i,
            "group_name": EXPERT_ROUTING[i]["name"],
            "task": EXPERT_ROUTING[i]["task"],
            "classes": EXPERT_ROUTING[i]["classes"],
            "probability": float(probs[i]),
            "send_to_expert": bool(predictions[i] >= threshold),
        })

    result = {
        "image_path": image_path,
        "probabilities": {
            "group1_od": float(probs[0]),
            "group2_seg1": float(probs[1]),
            "group3_seg2": float(probs[2]),
        },
        "decisions": {
            "group1_od": bool(predictions[0]),
            "group2_seg1": bool(predictions[1]),
            "group3_seg2": bool(predictions[2]),
        },
        "routing": routing,
        "threshold": threshold,
    }

    return result


def predict_batch(
    model: GatingModel,
    image_paths: List[str],
    threshold: float = 0.5,
    device: str = "cuda",
    batch_size: int = 32,
) -> List[Dict]:
    """
    批量推理

    Args:
        model: 门控模型
        image_paths: 图片路径列表
        threshold: 判定阈值
        device: 设备
        batch_size: 批次大小
    Returns:
        预测结果列表
    """
    results = []

    for i in range(0, len(image_paths), batch_size):
        batch_paths = image_paths[i:i + batch_size]
        batch_tensors = []

        for path in batch_paths:
            try:
                image = Image.open(path).convert("RGB")
                tensor = INFERENCE_TRANSFORM(image)
                batch_tensors.append(tensor)
            except Exception as e:
                print(f"[ERROR] 加载图片失败: {path}, {e}")
                # 用零张量占位
                batch_tensors.append(torch.zeros(3, 224, 224))

        if not batch_tensors:
            continue

        inputs = torch.stack(batch_tensors).to(device)

        with torch.no_grad():
            logits = model(inputs)
            probs = torch.sigmoid(logits)
            preds = (probs >= threshold).float()

        probs = probs.cpu().numpy()
        preds = preds.cpu().numpy()

        for j, path in enumerate(batch_paths):
            routing = []
            for k in range(3):
                routing.append({
                    "group_id": k,
                    "group_name": EXPERT_ROUTING[k]["name"],
                    "task": EXPERT_ROUTING[k]["task"],
                    "classes": EXPERT_ROUTING[k]["classes"],
                    "probability": float(probs[j][k]),
                    "send_to_expert": bool(preds[j][k]),
                })

            results.append({
                "image_path": path,
                "probabilities": {
                    "group1_od": float(probs[j][0]),
                    "group2_seg1": float(probs[j][1]),
                    "group3_seg2": float(probs[j][2]),
                },
                "decisions": {
                    "group1_od": bool(preds[j][0]),
                    "group2_seg1": bool(preds[j][1]),
                    "group3_seg2": bool(preds[j][2]),
                },
                "routing": routing,
                "threshold": threshold,
            })

    return results


def print_result(result: Dict):
    """格式化打印单张图片的推理结果"""
    print(f"\n{'='*60}")
    print(f"图片: {result['image_path']}")
    print(f"{'='*60}")
    print(f"阈值: {result['threshold']}")
    print(f"\n预测概率:")
    print(f"  Group1 (OD专家):   {result['probabilities']['group1_od']:.4f}  "
          f"→ {'✓ 分发' if result['decisions']['group1_od'] else '✗ 不分发'}")
    print(f"  Group2 (Seg专家1): {result['probabilities']['group2_seg1']:.4f}  "
          f"→ {'✓ 分发' if result['decisions']['group2_seg1'] else '✗ 不分发'}")
    print(f"  Group3 (Seg专家2): {result['probabilities']['group3_seg2']:.4f}  "
          f"→ {'✓ 分发' if result['decisions']['group3_seg2'] else '✗ 不分发'}")

    # 路由总结
    routed = [r for r in result["routing"] if r["send_to_expert"]]
    if len(routed) == 0:
        print(f"\n⚠ 该图片未被分发到任何专家模型")
    else:
        print(f"\n分发到 {len(routed)} 个专家模型:")
        for r in routed:
            print(f"  → {r['group_name']}")
            print(f"    任务: {r['task']}")
            print(f"    类别: {', '.join(r['classes'])}")
            print(f"    置信度: {r['probability']:.4f}")


def main():
    parser = argparse.ArgumentParser(description="门控模型推理")
    parser.add_argument("--model", type=str, required=True,
                        help="模型权重文件路径 (.pth)")
    parser.add_argument("--image", type=str, default=None,
                        help="单张图片路径")
    parser.add_argument("--image_dir", type=str, default=None,
                        help="图片目录（批量推理）")
    parser.add_argument("--output", type=str, default=None,
                        help="批量推理结果输出 JSON 文件路径")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="分类阈值")
    parser.add_argument("--device", type=str, default="auto",
                        help="设备: auto, cuda, cpu")
    parser.add_argument("--batch_size", type=int, default=32,
                        help="批量推理批次大小")
    parser.add_argument("--interactive", action="store_true",
                        help="交互模式：持续输入图片路径进行推理")
    args = parser.parse_args()

    # 加载模型
    print("加载门控模型...")
    model, meta = load_model(args.model, args.device)
    threshold = args.threshold if args.threshold != 0.5 else meta["threshold"]
    device = meta["device"]
    print(f"设备: {device}, 阈值: {threshold}")

    # 单张图片推理
    if args.image:
        result = predict_single(model, args.image, threshold, device)
        print_result(result)

    # 批量推理
    elif args.image_dir:
        image_dir = Path(args.image_dir)
        extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
        image_paths = sorted([
            str(p) for p in image_dir.iterdir()
            if p.suffix.lower() in extensions
        ])
        print(f"找到 {len(image_paths)} 张图片")

        results = predict_batch(model, image_paths, threshold, device, args.batch_size)

        # 统计
        total = len(results)
        g1_routed = sum(1 for r in results if r["decisions"]["group1_od"])
        g2_routed = sum(1 for r in results if r["decisions"]["group2_seg1"])
        g3_routed = sum(1 for r in results if r["decisions"]["group3_seg2"])
        multi_routed = sum(
            1 for r in results
            if sum(r["decisions"].values()) > 1
        )

        print(f"\n{'='*60}")
        print(f"批量推理统计 (共 {total} 张)")
        print(f"{'='*60}")
        print(f"  Group1 (OD):     {g1_routed} 张 ({g1_routed/total*100:.1f}%)")
        print(f"  Group2 (Seg1):   {g2_routed} 张 ({g2_routed/total*100:.1f}%)")
        print(f"  Group3 (Seg2):   {g3_routed} 张 ({g3_routed/total*100:.1f}%)")
        print(f"  多专家路由:      {multi_routed} 张")

        # 保存结果
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"\n结果已保存到: {args.output}")

    # 交互模式
    elif args.interactive:
        print("\n交互推理模式 (输入 'exit' 退出)")
        while True:
            try:
                img_path = input("\n图片路径: ").strip().strip('"').strip("'")
                if img_path.lower() == "exit":
                    break
                if not Path(img_path).exists():
                    print(f"[ERROR] 文件不存在: {img_path}")
                    continue
                result = predict_single(model, img_path, threshold, device)
                print_result(result)
            except KeyboardInterrupt:
                print("\n退出")
                break

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
