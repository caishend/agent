"""
门控模型：基于 ResNet-50 的多标签分类器

输出 3 个独立的 sigmoid 预测值，分别对应：
    - group1 (OD专家):  snow, water_accumulation, flood
    - group2 (Seg专家1): debris_flow, sinkhole, crack, landslide, rockfall
    - group3 (Seg专家2): pipe, construction_area

每个输出独立预测，一张图片可以同时属于多个组（多标签分类）。
"""

import torch
import torch.nn as nn
from torchvision.models import resnet50, ResNet50_Weights


class GatingModel(nn.Module):
    """
    ResNet-50 门控模型

    用 ResNet-50 作为 backbone，替换最后的全连接层为 3 个输出节点，
    每个节点使用 sigmoid 独立预测。
    """

    def __init__(self, num_groups: int = 3, pretrained: bool = True, freeze_backbone: bool = False):
        """
        Args:
            num_groups: 输出组数（默认3：OD专家、Seg专家1、Seg专家2）
            pretrained: 是否使用 ImageNet 预训练权重
            freeze_backbone: 是否冻结 backbone（仅训练分类头）
        """
        super().__init__()

        # 加载预训练 ResNet-50
        if pretrained:
            weights = ResNet50_Weights.IMAGENET1K_V2
            self.backbone = resnet50(weights=weights)
        else:
            self.backbone = resnet50(weights=None)

        # 冻结 backbone
        if freeze_backbone:
            for param in self.backbone.parameters():
                param.requires_grad = False

        # 替换最后的全连接层
        in_features = self.backbone.fc.in_features
        self.backbone.fc = nn.Sequential(
            nn.Dropout(p=0.3),
            nn.Linear(in_features, 512),
            nn.ReLU(inplace=True),
            nn.Dropout(p=0.3),
            nn.Linear(512, num_groups),
        )

        # 注意：不使用 Sigmoid 层，因为使用 BCEWithLogitsLoss 时内部包含了 sigmoid

    def forward(self, x):
        """
        Args:
            x: 输入图片 Tensor (B, 3, H, W)
        Returns:
            logits: Tensor (B, 3) 原始 logits（未经过 sigmoid）
        """
        return self.backbone(x)

    def predict(self, x, threshold: float = 0.5):
        """
        推理模式：返回概率和二元预测

        Args:
            x: 输入图片 Tensor (B, 3, H, W)
            threshold: 判定为正类的阈值
        Returns:
            probs: Tensor (B, 3) sigmoid 概率值
            predictions: Tensor (B, 3) 二元预测 (0/1)
        """
        with torch.no_grad():
            logits = self.forward(x)
            probs = torch.sigmoid(logits)
            predictions = (probs >= threshold).float()
        return probs, predictions

    def get_group_names(self):
        """返回各组名称"""
        return [
            "Group1 (OD): snow, water_accumulation, flood",
            "Group2 (Seg): debris_flow, sinkhole, crack, landslide, rockfall",
            "Group3 (Seg): pipe, construction_area",
        ]


def create_model(freeze_backbone: bool = False, device: str = "cuda") -> GatingModel:
    """
    创建门控模型的工厂函数

    Args:
        freeze_backbone: 第一阶段训练时设为 True
        device: "cuda" 或 "cpu"
    Returns:
        model: GatingModel 实例
    """
    model = GatingModel(
        num_groups=3,
        pretrained=True,
        freeze_backbone=freeze_backbone,
    )
    model = model.to(device)
    return model


if __name__ == "__main__":
    # 测试模型
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"设备: {device}")

    model = create_model(device=device)
    print(model)

    # 测试前向传播
    dummy_input = torch.randn(4, 3, 224, 224).to(device)
    logits = model(dummy_input)
    print(f"\n输入形状: {dummy_input.shape}")
    print(f"输出 logits 形状: {logits.shape}")

    probs, preds = model.predict(dummy_input)
    print(f"概率: {probs}")
    print(f"预测: {preds}")

    # 统计参数量
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"\n总参数量: {total_params:,}")
    print(f"可训练参数量: {trainable_params:,}")
