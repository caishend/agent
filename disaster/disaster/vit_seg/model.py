"""ViT-Small + UNet-style decoder for semantic segmentation.

Based on: vit_small_patch16_224 (timm)
Decoder:  progressive upsampling without skip connections
          (ViT has no hierarchical features)

Supports offline use via a local .pth checkpoint with automatic
pos_embed resizing when image_size differs from the pretrained 224.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import timm
from timm.models.vision_transformer import resize_pos_embed


class ConvBnRelu(nn.Sequential):
    def __init__(self, in_ch, out_ch):
        super().__init__(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )


class DecoderBlock(nn.Module):
    """2× upsample → double conv."""
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.conv = nn.Sequential(
            ConvBnRelu(in_ch, out_ch),
            ConvBnRelu(out_ch, out_ch),
        )

    def forward(self, x):
        x = F.interpolate(x, scale_factor=2, mode="bilinear", align_corners=False)
        return self.conv(x)


class ViTSeg(nn.Module):
    """ViT-Small encoder + progressive UNet-style decoder.

    ViT outputs flat patch tokens (B, N, C); we reshape to a spatial
    feature map (B, C, H/16, W/16) and upsample back to full resolution.

    Args:
        num_classes:      output classes
        img_size:         input spatial size (must be divisible by 16)
        checkpoint_path:  path to local .pth file (timm or custom format).
                          Pass None to download from the internet.
    """

    PATCH_SIZE = 16
    EMBED_DIM  = 384   # vit_small

    def __init__(self, num_classes: int = 6,
                 img_size: int = 224,
                 checkpoint_path: str = None):
        super().__init__()
        self.grid_size = img_size // self.PATCH_SIZE

        self.encoder = timm.create_model(
            "vit_small_patch16_224",
            pretrained=(checkpoint_path is None),
            img_size=img_size,
            num_classes=0,
        )

        if checkpoint_path is not None:
            state = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
            # unwrap common wrappers
            for key in ("state_dict", "model"):
                if isinstance(state, dict) and key in state:
                    state = state[key]
            # strip DDP prefix
            if isinstance(state, dict) and any(k.startswith("module.") for k in state):
                state = {k.replace("module.", "", 1): v for k, v in state.items()}
            # resize pos_embed if resolution changed
            if isinstance(state, dict) and "pos_embed" in state:
                if state["pos_embed"].shape != self.encoder.pos_embed.shape:
                    state["pos_embed"] = resize_pos_embed(
                        state["pos_embed"],
                        self.encoder.pos_embed,
                        num_prefix_tokens=1,
                        gs_new=(self.grid_size, self.grid_size),
                    )
            self.encoder.load_state_dict(state, strict=False)

        # Decoder: grid_size → img_size  (4 doublings for patch_size=16)
        self.dec4 = DecoderBlock(self.EMBED_DIM, 256)
        self.dec3 = DecoderBlock(256, 128)
        self.dec2 = DecoderBlock(128,  64)
        self.dec1 = DecoderBlock( 64,  32)
        self.head = nn.Conv2d(32, num_classes, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (B, 3, H, W)
        Returns:
            (B, num_classes, H, W) raw logits
        """
        tokens = self.encoder.forward_features(x)     # (B, N+1, C)
        patch_tokens = tokens[:, 1:, :]               # drop CLS → (B, N, C)
        B, N, C = patch_tokens.shape
        H = W = self.grid_size
        feat = patch_tokens.permute(0, 2, 1).reshape(B, C, H, W)

        feat = self.dec4(feat)
        feat = self.dec3(feat)
        feat = self.dec2(feat)
        feat = self.dec1(feat)
        return self.head(feat)

    def param_groups(self, lr_backbone: float, lr_head: float) -> list:
        """Differential LR: lower for pretrained encoder, higher for decoder."""
        return [
            {"params": list(self.encoder.parameters()), "lr": lr_backbone},
            {"params": (list(self.dec4.parameters()) + list(self.dec3.parameters()) +
                        list(self.dec2.parameters()) + list(self.dec1.parameters()) +
                        list(self.head.parameters())),  "lr": lr_head},
        ]
