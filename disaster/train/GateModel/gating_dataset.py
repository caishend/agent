"""
门控模型数据集类
读取 new_dataset/ 中的整合数据，输出图片和3个二分类标签
"""

import os
import pandas as pd
from PIL import Image
from pathlib import Path

import torch
from torch.utils.data import Dataset
from torchvision import transforms


class GatingDataset(Dataset):
    """
    门控模型数据集

    每张图片返回:
        image: Tensor (3, H, W)
        labels: Tensor([group1, group2, group3])  每个值为 0 或 1
    """

    def __init__(
        self,
        data_dir: str,
        labels_csv: str,
        split: str = "train",
        train_ratio: float = 0.7,
        val_ratio: float = 0.15,
        seed: int = 42,
        transform=None,
    ):
        """
        Args:
            data_dir: new_dataset 根目录路径
            labels_csv: labels.csv 文件路径
            split: "train", "val", 或 "test"
            train_ratio: 训练集比例
            val_ratio: 验证集比例
            seed: 随机种子
            transform: 自定义 transform，None 则使用默认
        """
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "images"
        self.split = split

        # 读取标签
        self.df = pd.read_csv(labels_csv)

        # 分层划分 train/val/test（按 sub_class 分层）
        from sklearn.model_selection import train_test_split

        # 先分出 train 和 temp(val+test)
        train_df, temp_df = train_test_split(
            self.df,
            test_size=(1 - train_ratio),
            random_state=seed,
            stratify=self.df["sub_class"],
        )

        # 再从 temp 分出 val 和 test
        val_ratio_adjusted = val_ratio / (1 - train_ratio)  # 相对于 temp 的比例
        val_df, test_df = train_test_split(
            temp_df,
            test_size=(1 - val_ratio_adjusted),
            random_state=seed,
            stratify=temp_df["sub_class"],
        )

        if split == "train":
            self.df = train_df.reset_index(drop=True)
        elif split == "val":
            self.df = val_df.reset_index(drop=True)
        elif split == "test":
            self.df = test_df.reset_index(drop=True)
        else:
            raise ValueError(f"未知的 split: {split}")

        # 构建标签数组
        self.labels = torch.tensor(
            self.df[["group1", "group2", "group3"]].values, dtype=torch.float32
        )

        # 默认 transform
        if transform is None:
            if split == "train":
                self.transform = transforms.Compose([
                    transforms.Resize((224, 224)),
                    transforms.RandomHorizontalFlip(p=0.5),
                    transforms.RandomRotation(degrees=10),
                    transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.1),
                    transforms.ToTensor(),
                    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                         std=[0.229, 0.224, 0.225]),
                ])
            else:
                self.transform = transforms.Compose([
                    transforms.Resize((224, 224)),
                    transforms.ToTensor(),
                    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                         std=[0.229, 0.224, 0.225]),
                ])
        else:
            self.transform = transform

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        img_path = self.images_dir / row["image_name"]

        # 加载图片，处理可能的格式问题
        try:
            image = Image.open(img_path).convert("RGB")
        except Exception as e:
            print(f"[ERROR] 无法加载图片: {img_path}, 错误: {e}")
            # 返回一张空白图
            image = Image.new("RGB", (224, 224))

        if self.transform:
            image = self.transform(image)

        labels = self.labels[idx]

        return image, labels

    def get_class_weights(self):
        """
        计算各类别的正样本权重，用于处理不平衡问题
        返回: Tensor([w1, w2, w3]) 每个group的正样本权重
        """
        pos_counts = self.labels.sum(dim=0)  # [group1正样本数, group2, group3]
        neg_counts = len(self.labels) - pos_counts

        # pos_weight = neg / pos (用于 BCEWithLogitsLoss)
        pos_weight = neg_counts / (pos_counts + 1e-8)
        return pos_weight

    def get_split_info(self):
        """返回当前split的统计信息"""
        total = len(self.df)
        g1 = int(self.labels[:, 0].sum().item())
        g2 = int(self.labels[:, 1].sum().item())
        g3 = int(self.labels[:, 2].sum().item())
        return {
            "split": self.split,
            "total": total,
            "group1": g1,
            "group2": g2,
            "group3": g3,
        }


if __name__ == "__main__":
    # 测试数据集加载
    import sys

    data_dir = Path(__file__).parent / "new_dataset"
    labels_csv = data_dir / "labels.csv"

    if not labels_csv.exists():
        print("请先运行 integrate_dataset.py 生成数据集")
        sys.exit(1)

    for split in ["train", "val", "test"]:
        ds = GatingDataset(str(data_dir), str(labels_csv), split=split)
        info = ds.get_split_info()
        print(f"{split}: total={info['total']}, "
              f"G1={info['group1']}, G2={info['group2']}, G3={info['group3']}")

        if len(ds) > 0:
            img, labels = ds[0]
            print(f"  图片形状: {img.shape}, 标签: {labels}")
            print(f"  pos_weight: {ds.get_class_weights()}")
