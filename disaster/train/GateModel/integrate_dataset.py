"""
数据整合脚本：从原始 dataset/ 目录整合所有图片和标签到 new_dataset/
原始 dataset 目录不做任何改动。

输出结构：
    new_dataset/
    ├── images/          # 所有图片（带前缀避免重名）
    └── labels.csv       # image_name, group1, group2, group3, sub_class

分组规则：
    Group1 (OD专家):      snow, water_accumulation, flood
    Group2 (Seg专家1):    debris_flow, sinkhole, crack, landslide, rockfall
    Group3 (Seg专家2):    pipe, construction_area
"""

import os
import shutil
import csv
from pathlib import Path

# ============ 配置 ============
DATASET_DIR = Path(__file__).parent / "dataset"
NEW_DATASET_DIR = Path(__file__).parent / "new_dataset"
NEW_IMAGES_DIR = NEW_DATASET_DIR / "images"

# 分组定义
GROUP1_CLASSES = ["snow", "water_accumulation", "flood"]        # → OD专家
GROUP2_CLASSES = ["debris_flow", "sinkhole", "crack", "landslide", "rockfall"]  # → Seg专家1
GROUP3_CLASSES = ["pipe", "construction_area"]                  # → Seg专家2


def create_dirs():
    """创建输出目录"""
    NEW_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[OK] 创建目录: {NEW_IMAGES_DIR}")


def process_group1():
    """
    处理 Group1：snow, water_accumulation, flood
    原始结构: dataset/group1/{class}/images/*.png(jpg) + labels/*.txt
    标签格式: 1\t{class_name}
    映射: group1=1, group2=0, group3=0
    """
    records = []
    for class_name in GROUP1_CLASSES:
        class_dir = DATASET_DIR / "group1" / class_name
        images_dir = class_dir / "images"
        labels_dir = class_dir / "labels"

        if not images_dir.exists():
            print(f"[WARN] 目录不存在: {images_dir}")
            continue

        for img_file in images_dir.iterdir():
            if not img_file.is_file():
                continue
            # 新文件名: g1_{class}_{original_name}
            new_name = f"g1_{class_name}_{img_file.name}"
            dst_path = NEW_IMAGES_DIR / new_name
            shutil.copy2(img_file, dst_path)

            # 验证标签文件存在
            label_file = labels_dir / (img_file.stem + ".txt")
            if label_file.exists():
                records.append({
                    "image_name": new_name,
                    "group1": 1,
                    "group2": 0,
                    "group3": 0,
                    "sub_class": class_name,
                })

        print(f"[OK] Group1/{class_name}: {len([r for r in records if r['sub_class'] == class_name])} 张图片")

    return records


def process_group2():
    """
    处理 Group2：debris_flow, sinkhole, crack, landslide, rockfall
    原始结构: dataset/group2/{train,valid}/*.jpg
    标签来源: 文件名前缀 {class}__
    映射: group1=0, group2=1, group3=0
    """
    records = []
    for split in ["train", "valid"]:
        split_dir = DATASET_DIR / "group2" / split
        if not split_dir.exists():
            print(f"[WARN] 目录不存在: {split_dir}")
            continue

        for img_file in split_dir.iterdir():
            if not img_file.is_file():
                continue
            # 从文件名解析类别: "crack__crack_IMG_xxx.jpg" → class="crack"
            parts = img_file.name.split("__")
            if len(parts) < 2:
                print(f"[WARN] 无法解析类别: {img_file.name}")
                continue
            class_name = parts[0]
            if class_name not in GROUP2_CLASSES:
                print(f"[WARN] 未知类别: {class_name} in {img_file.name}")
                continue

            # 新文件名: g2_{class}_{split}_{original_name}
            new_name = f"g2_{class_name}_{split}_{img_file.name}"
            dst_path = NEW_IMAGES_DIR / new_name
            shutil.copy2(img_file, dst_path)

            records.append({
                "image_name": new_name,
                "group1": 0,
                "group2": 1,
                "group3": 0,
                "sub_class": class_name,
            })

    for cls in GROUP2_CLASSES:
        cnt = len([r for r in records if r['sub_class'] == cls])
        print(f"[OK] Group2/{cls}: {cnt} 张图片")

    return records


def process_group3():
    """
    处理 Group3：pipe, construction_area
    原始结构: dataset/group3/images/*.jpg + labels/*.txt
    标签格式: 第一行为类名（pipe 或 construction_area）
    映射: group1=0, group2=0, group3=1
    """
    records = []
    images_dir = DATASET_DIR / "group3" / "images"
    labels_dir = DATASET_DIR / "group3" / "labels"

    if not images_dir.exists():
        print(f"[WARN] 目录不存在: {images_dir}")
        return records

    for img_file in images_dir.iterdir():
        if not img_file.is_file():
            continue

        # 新文件名: g3_{original_name}
        new_name = f"g3_{img_file.name}"
        dst_path = NEW_IMAGES_DIR / new_name
        shutil.copy2(img_file, dst_path)

        # 读标签
        label_file = labels_dir / (img_file.stem + ".txt")
        sub_class = "unknown"
        if label_file.exists():
            with open(label_file, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                # 格式可能是 "1\tpipe" 或 "pipe"
                if "\t" in first_line:
                    sub_class = first_line.split("\t")[-1].strip()
                else:
                    sub_class = first_line.strip()

        if sub_class not in GROUP3_CLASSES:
            print(f"[WARN] 未知类别 '{sub_class}' for {img_file.name}, 跳过")
            # 删除已复制的图片
            dst_path.unlink(missing_ok=True)
            continue

        records.append({
            "image_name": new_name,
            "group1": 0,
            "group2": 0,
            "group3": 1,
            "sub_class": sub_class,
        })

    for cls in GROUP3_CLASSES:
        cnt = len([r for r in records if r['sub_class'] == cls])
        print(f"[OK] Group3/{cls}: {cnt} 张图片")

    return records


def write_labels_csv(records):
    """写入 labels.csv"""
    csv_path = NEW_DATASET_DIR / "labels.csv"
    fieldnames = ["image_name", "group1", "group2", "group3", "sub_class"]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"\n[OK] 标签文件写入: {csv_path}")
    print(f"[OK] 总计 {len(records)} 条记录")


def print_statistics(records):
    """打印数据集统计"""
    print("\n" + "=" * 60)
    print("数据集统计")
    print("=" * 60)

    total = len(records)
    g1_cnt = sum(1 for r in records if r["group1"] == 1)
    g2_cnt = sum(1 for r in records if r["group2"] == 1)
    g3_cnt = sum(1 for r in records if r["group3"] == 1)

    print(f"总图片数:        {total}")
    print(f"Group1 (OD):     {g1_cnt} ({g1_cnt/total*100:.1f}%)")
    print(f"Group2 (Seg1):   {g2_cnt} ({g2_cnt/total*100:.1f}%)")
    print(f"Group3 (Seg2):   {g3_cnt} ({g3_cnt/total*100:.1f}%)")

    print("\n各类别分布:")
    from collections import Counter
    class_counts = Counter(r["sub_class"] for r in records)
    for cls, cnt in sorted(class_counts.items(), key=lambda x: -x[1]):
        group = "G1(OD)" if cls in GROUP1_CLASSES else ("G2(Seg1)" if cls in GROUP2_CLASSES else "G3(Seg2)")
        print(f"  {cls:25s} {group:10s} {cnt:5d} 张")


def main():
    print("=" * 60)
    print("门控模型数据集整合")
    print("=" * 60)

    create_dirs()

    all_records = []
    all_records.extend(process_group1())
    all_records.extend(process_group2())
    all_records.extend(process_group3())

    write_labels_csv(all_records)
    print_statistics(all_records)

    print("\n[完成] 数据集整合完毕，原始 dataset/ 目录未改动。")


if __name__ == "__main__":
    main()
