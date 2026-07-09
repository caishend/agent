"""
视频逐帧推理 + 重编码

流程：
1. OpenCV 逐帧推理，用 mp4v 写出临时视频（所有平台均可用）
2. 用 ffmpeg 将 mp4v 转码为 H.264 MP4（浏览器可预览）
3. 若无 ffmpeg，保留 mp4v 文件（可下载，浏览器预览可能不支持）
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
from PIL import Image

from backend.inference import run_on_image


def _find_ffmpeg() -> str | None:
    """在 PATH 或常见位置查找 ffmpeg 可执行文件。"""
    candidates = ["ffmpeg", "ffmpeg.exe"]
    # Windows 常见安装路径
    if sys.platform == "win32":
        candidates.extend([
            str(Path.home() / "scoop" / "shims" / "ffmpeg.exe"),
            str(Path("C:/") / "ffmpeg" / "bin" / "ffmpeg.exe"),
        ])
    for name in candidates:
        if shutil.which(name):
            return name
    return None


def process_video(input_path: Path, output_path: Path, threshold: float | None = None) -> int:
    """
    逐帧推理输入视频，写出带标注的 H.264 MP4 视频（浏览器可预览）。
    返回总帧数。
    """
    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {input_path}")

    fps: float = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width: int = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height: int = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total: int = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 第一步：用 mp4v 写出推理结果（所有平台通用，不依赖 OpenH264） ──
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    middle_path = output_path.with_suffix(".tmp.mp4")
    writer = cv2.VideoWriter(str(middle_path), fourcc, fps, (width, height))

    frame_idx = 0
    try:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break

            image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
            annotated_bgr, _ = run_on_image(image, threshold)

            if annotated_bgr.shape[1] != width or annotated_bgr.shape[0] != height:
                annotated_bgr = cv2.resize(annotated_bgr, (width, height))

            writer.write(annotated_bgr)
            frame_idx += 1

            if frame_idx % 50 == 0:
                print(f"  [video] {frame_idx}/{total} frames")
    finally:
        cap.release()
        writer.release()

    # ── 第二步：用 ffmpeg 转码为浏览器可播放的 H.264 MP4 ──
    _transcode_to_h264(middle_path, output_path)

    return frame_idx


def _transcode_to_h264(middle_path: Path, output_path: Path) -> None:
    """把 mp4v 中间文件转码为浏览器可播放的 H.264 MP4；无 ffmpeg 时回退。"""
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        print("  [video] 正在用 ffmpeg 转码为 H.264...")
        result = subprocess.run(
            [
                ffmpeg, "-y",
                "-i", str(middle_path),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(output_path),
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  [video] ⚠️ ffmpeg 转码失败：{result.stderr[-300:]}")
            # 转码失败时回退：把 mp4v 文件作为最终输出
            middle_path.rename(output_path)
            print("  [video] 退回使用 mp4v 编码（浏览器可能无法预览）")
        else:
            middle_path.unlink(missing_ok=True)  # 删除中间文件
            print("  [video] H.264 转码完成，浏览器可预览")
    else:
        print("  [video] ⚠️ 未找到 ffmpeg，输出为 mp4v 编码（浏览器可能无法预览）")
        print("  [video] 提示：安装 ffmpeg 并加入 PATH 后可自动转码为 H.264")
        middle_path.rename(output_path)


def _encode_preview(bgr: np.ndarray, max_side: int = 720, quality: int = 80) -> str:
    """把 BGR 帧缩放并编码为 data:image/jpeg;base64，用于前端实时预览。"""
    h, w = bgr.shape[:2]
    scale = min(1.0, max_side / float(max(h, w)))
    if scale < 1.0:
        bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")


def process_video_stream(
    input_path: Path,
    output_path: Path,
    threshold: float | None = None,
    preview_max_side: int = 720,
    jpeg_quality: int = 80,
) -> Iterator[dict]:
    """
    逐帧推理输入视频并实时产出事件（供 SSE 推送）。

    依次 yield:
        {"type": "frame", "frame_idx", "total", "image", "detections", "segmentations"}
        ...
        {"type": "done", "result_name", "frame_count"}
    出错时 yield {"type": "error", "message": ...}
    """
    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        yield {"type": "error", "message": f"无法打开视频: {input_path}"}
        return

    fps: float = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width: int = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height: int = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total: int = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    middle_path = output_path.with_suffix(".tmp.mp4")
    writer = cv2.VideoWriter(str(middle_path), fourcc, fps, (width, height))

    frame_idx = 0
    try:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break

            image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
            annotated_bgr, structured = run_on_image(image, threshold)

            if annotated_bgr.shape[1] != width or annotated_bgr.shape[0] != height:
                annotated_bgr = cv2.resize(annotated_bgr, (width, height))

            writer.write(annotated_bgr)
            frame_idx += 1

            yield {
                "type": "frame",
                "frame_idx": frame_idx,
                "total": total,
                "image": _encode_preview(annotated_bgr, preview_max_side, jpeg_quality),
                "detections": [d.model_dump() for d in structured["detections"]],
                "segmentations": [s.model_dump() for s in structured["segmentations"]],
            }
    finally:
        cap.release()
        writer.release()

    _transcode_to_h264(middle_path, output_path)

    yield {"type": "done", "result_name": output_path.name, "frame_count": frame_idx}
