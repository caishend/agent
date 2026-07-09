"""Loss functions for multi-class semantic segmentation."""

import torch
import torch.nn as nn
import torch.nn.functional as F


class MultiClassDiceLoss(nn.Module):
    """Mean Dice loss over all classes (macro), excluding background by default."""

    def __init__(self, num_classes: int, smooth: float = 1.0, ignore_bg: bool = False):
        super().__init__()
        self.num_classes = num_classes
        self.smooth = smooth
        self.ignore_bg = ignore_bg  # if True, skip class index (num_classes-1)

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """
        Args:
            pred:   (B, C, H, W) logits
            target: (B, H, W) long class indices
        """
        prob = F.softmax(pred, dim=1)                        # (B, C, H, W)
        target_one_hot = F.one_hot(target, self.num_classes) \
                          .permute(0, 3, 1, 2).float()       # (B, C, H, W)

        classes = range(self.num_classes - 1) if self.ignore_bg else range(self.num_classes)
        dice_losses = []
        for c in classes:
            p = prob[:, c].reshape(-1)
            t = target_one_hot[:, c].reshape(-1)
            intersection = (p * t).sum()
            dice = (2.0 * intersection + self.smooth) / (p.sum() + t.sum() + self.smooth)
            dice_losses.append(1.0 - dice)

        return torch.stack(dice_losses).mean()


class CEDiceLoss(nn.Module):
    """CrossEntropy + Dice loss for multi-class segmentation.

    Loss = alpha * CE + beta * Dice
    """

    def __init__(self, num_classes: int, alpha: float = 0.5, beta: float = 0.5,
                 ignore_bg: bool = False):
        super().__init__()
        self.alpha = alpha
        self.beta = beta
        self.ce = nn.CrossEntropyLoss()
        self.dice = MultiClassDiceLoss(num_classes, ignore_bg=ignore_bg)

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """
        Args:
            pred:   (B, C, H, W) logits
            target: (B, H, W) long class indices
        """
        ce_loss = self.ce(pred, target)
        dice_loss = self.dice(pred, target)
        return self.alpha * ce_loss + self.beta * dice_loss


# Keep old name as alias for any leftover imports
BCEDiceLoss = CEDiceLoss
