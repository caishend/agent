import sys
from pathlib import Path

import torch
from PIL import Image
from torchvision import transforms

_ROOT = Path(__file__).parent.parent.parent
for _gate_model_dir in (_ROOT / "GateModel", _ROOT / "train" / "GateModel"):
    if _gate_model_dir.exists() and str(_gate_model_dir) not in sys.path:
        sys.path.insert(0, str(_gate_model_dir))
from gating_model import GatingModel

INFERENCE_TRANSFORM = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def load(weights_path: Path, device: torch.device) -> tuple:
    ckpt = torch.load(weights_path, map_location=device, weights_only=False)
    threshold = ckpt.get("threshold", 0.5)
    model = GatingModel(num_groups=3, pretrained=False)
    model.load_state_dict(ckpt["model_state_dict"])
    model.to(device).eval()
    return model, threshold


@torch.no_grad()
def predict(model, image: Image.Image, threshold: float, device: torch.device) -> dict:
    tensor = INFERENCE_TRANSFORM(image).unsqueeze(0).to(device)
    logits = model(tensor)
    probs = torch.sigmoid(logits).cpu().numpy()[0]   # (3,)
    decisions = (probs >= threshold)

    return {
        "probabilities": {
            "group1_od":   float(probs[0]),
            "group2_seg1": float(probs[1]),
            "group3_seg2": float(probs[2]),
        },
        "decisions": {
            "group1_od":   bool(decisions[0]),
            "group2_seg1": bool(decisions[1]),
            "group3_seg2": bool(decisions[2]),
        },
        "threshold": threshold,
    }
