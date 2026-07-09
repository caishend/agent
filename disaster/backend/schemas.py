"""
请求/响应数据模型
"""

from typing import Any, Optional
from pydantic import BaseModel


class Detection(BaseModel):
    class_id:   int
    class_name: str
    confidence: float
    box_xyxy:   list[float]   # [x1, y1, x2, y2]


class Segmentation(BaseModel):
    class_name:   str
    pixel_count:  int
    pixel_ratio:  float


class GateInfo(BaseModel):
    probabilities: dict[str, float]
    decisions:     dict[str, bool]
    threshold:     float


class ImageResponse(BaseModel):
    code:        int = 0
    msg:         str = "success"
    image_path:  str
    gate:        GateInfo
    detections:  list[Detection]        = []
    segmentations: list[Segmentation]   = []


class VideoResponse(BaseModel):
    code:        int = 0
    msg:         str = "success"
    video_path:  str
    frame_count: int


class AnalysisRequest(BaseModel):
    target: str
    result: dict[str, Any]


class AnalysisResponse(BaseModel):
    code: int = 0
    msg: str = "success"
    content: str


class ErrorResponse(BaseModel):
    code: int
    msg:  str
