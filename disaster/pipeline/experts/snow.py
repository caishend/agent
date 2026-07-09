import torch
from pathlib import Path
from PIL import Image
import numpy as np
import cv2
from ultralytics import YOLO

CLASS_NAMES = ["snow", "water_accumulation", "flood"]

_model: YOLO | None = None


def load(weights_path: Path, device: torch.device) -> YOLO:
    global _model
    _model = YOLO(str(weights_path))
    return _model


def predict(
    model: YOLO,
    image: Image.Image,
    conf: float,
    iou: float,
    imgsz: int,
    device: torch.device,
) -> dict:
    # PIL → numpy BGR for ultralytics
    img_np = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    device_str = str(device) if device.type != "cuda" else device.index if device.index is not None else 0

    results = model.predict(
        source=img_np,
        imgsz=imgsz,
        conf=conf,
        iou=iou,
        device=device_str,
        verbose=False,
    )[0]

    detections = []
    if results.boxes is not None:
        boxes  = results.boxes.xyxy.cpu().tolist()
        clses  = results.boxes.cls.cpu().tolist()
        confs  = results.boxes.conf.cpu().tolist()
        for box, cls_id, score in zip(boxes, clses, confs):
            cls_id = int(cls_id)
            detections.append({
                "class_id":   cls_id,
                "class_name": CLASS_NAMES[cls_id] if cls_id < len(CLASS_NAMES) else str(cls_id),
                "confidence": round(float(score), 4),
                "box_xyxy":   [round(v, 1) for v in box],
            })

    return {"detections": detections}


def draw(image: Image.Image, result: dict) -> Image.Image:
    img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    for det in result["detections"]:
        x1, y1, x2, y2 = [int(v) for v in det["box_xyxy"]]
        label = f"{det['class_name']} {det['confidence']:.2f}"
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 180, 0), 2)
        cv2.putText(img, label, (x1, max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 180, 0), 2, cv2.LINE_AA)
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
