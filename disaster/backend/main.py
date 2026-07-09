"""
FastAPI 后端入口

启动:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import cv2
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend import inference
from backend.schemas import AnalysisRequest, AnalysisResponse, ErrorResponse, ImageResponse, VideoResponse
from backend.video import process_video, process_video_stream

# ── 目录 ──────────────────────────────────────────────────────────────────────
_ROOT       = Path(__file__).parent.parent
_UPLOAD_DIR = _ROOT / "backend_output" / "uploads"
_RESULT_DIR = _ROOT / "backend_output" / "results"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_RESULT_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".wmv"}
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# ── 应用 ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Disaster Inspection API", version="1.0.0")

# 静态文件服务，前端可直接访问结果图/视频
app.mount("/files", StaticFiles(directory=str(_RESULT_DIR)), name="files")


@app.on_event("startup")
async def _startup():
    # 预加载所有模型，避免第一次请求时卡住
    inference.get_pipeline()


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _save_upload(file: UploadFile, dest_dir: Path) -> Path:
    suffix = Path(file.filename).suffix.lower()
    dest   = dest_dir / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(file.file.read())
    return dest


def _result_url(path: Path) -> str:
    return f"/files/{path.name}"


def _build_analysis_prompt(payload: dict) -> str:
    return (
        "请解析以下多模型识别结果，并给出面向用户展示的专业说明。\n"
        "要求：输出中文；分为“结论摘要、关键依据、风险与不确定性、复核建议”；"
        "不要夸大模型结论，不要给医疗、法律或灾害处置的最终决策。\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _request_deepseek(payload: dict) -> str:
    if not DEEPSEEK_API_KEY:
        raise HTTPException(500, "DeepSeek API Key 未配置，请设置 DEEPSEEK_API_KEY 环境变量")

    body = {
        "model": "deepseek-v4-pro",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个严谨的工程检测结果分析助手。"
                    "请基于识别结果做客观解读，帮助用户理解结果和后续复核重点。"
                ),
            },
            {"role": "user", "content": _build_analysis_prompt(payload)},
        ],
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
        "max_tokens": 1200,
        "stream": False,
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(502, f"DeepSeek 请求失败: {detail or exc.reason}")
    except Exception as exc:
        raise HTTPException(502, f"DeepSeek 请求失败: {exc}")

    return response_data.get("choices", [{}])[0].get("message", {}).get("content", "")


# ── 接口：图片推理 ────────────────────────────────────────────────────────────

@app.post("/predict/image", response_model=ImageResponse)
async def predict_image(file: UploadFile = File(...), threshold: float | None = None):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in IMAGE_EXTS:
        raise HTTPException(400, f"不支持的图片格式: {suffix}")

    upload_path = _save_upload(file, _UPLOAD_DIR)

    try:
        from PIL import Image as PILImage
        image = PILImage.open(upload_path).convert("RGB")
        annotated_bgr, structured = inference.run_on_image(image, threshold)
    except Exception as e:
        raise HTTPException(500, f"推理失败: {e}")

    result_name = f"{upload_path.stem}_result.jpg"
    result_path = _RESULT_DIR / result_name
    cv2.imwrite(str(result_path), annotated_bgr)

    return ImageResponse(
        image_path=_result_url(result_path),
        gate=structured["gate"],
        detections=structured["detections"],
        segmentations=structured["segmentations"],
    )


# ── 接口：视频推理 ────────────────────────────────────────────────────────────

@app.post("/predict/video", response_model=VideoResponse)
async def predict_video(file: UploadFile = File(...), threshold: float | None = None):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in VIDEO_EXTS:
        raise HTTPException(400, f"不支持的视频格式: {suffix}")

    upload_path = _save_upload(file, _UPLOAD_DIR)
    result_path = _RESULT_DIR / f"{upload_path.stem}_result.mp4"

    try:
        frame_count = process_video(upload_path, result_path, threshold)
    except Exception as e:
        raise HTTPException(500, f"视频推理失败: {e}")

    return VideoResponse(
        video_path=_result_url(result_path),
        frame_count=frame_count,
    )


# ── 接口：视频推理（实时流式 SSE）────────────────────────────────────────────

@app.post("/predict/video/stream")
async def predict_video_stream(file: UploadFile = File(...), threshold: float | None = None):
    """逐帧推理并以 SSE 实时推送标注画面，处理结束后返回最终视频地址。"""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in VIDEO_EXTS:
        raise HTTPException(400, f"不支持的视频格式: {suffix}")

    upload_path = _save_upload(file, _UPLOAD_DIR)
    result_path = _RESULT_DIR / f"{upload_path.stem}_result.mp4"

    def event_stream():
        try:
            for event in process_video_stream(upload_path, result_path, threshold):
                if event.get("type") == "done":
                    event["video_path"] = _result_url(result_path)
                    event.pop("result_name", None)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 — 把异常作为事件回传前端
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭反向代理缓冲，保证实时推送
        },
    )


# ── 接口：直接下载结果文件 ────────────────────────────────────────────────────

@app.get("/download/{filename}")
async def download(filename: str):
    path = _RESULT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(path), filename=filename)


@app.get("/original/{filename}")
async def get_original(filename: str):
    """直接返回上传目录中的原文件（用于前端展示原图）。"""
    path = _UPLOAD_DIR / filename
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(path))


# ── 接口：历史记录 ────────────────────────────────────────────────────────────

@app.get("/history")
async def get_history():
    """扫描 backend_output 文件夹，返回原图与结果图的配对列表。"""
    items: list[dict] = []

    # 收集结果文件 (xxx_result.jpg / xxx_result.mp4)
    result_files: dict[str, Path] = {}
    for f in sorted(_RESULT_DIR.iterdir()):
        if not f.is_file():
            continue
        # 匹配 *_result.ext 格式
        if "_result." in f.name:
            base = f.name.rsplit("_result", 1)[0]  # uuid 部分
            result_files[base] = f

    # 收集上传文件并配对
    for f in sorted(_UPLOAD_DIR.iterdir()):
        if not f.is_file():
            continue
        stem = f.stem  # uuid (不含扩展名)
        if stem in result_files:
            rfile = result_files[stem]
            is_video = rfile.suffix.lower() in VIDEO_EXTS
            items.append({
                "id": stem,
                "original_url": f"/original/{f.name}",
                "result_url": f"/files/{rfile.name}",
                "original_name": f.name,
                "result_name": rfile.name,
                "type": "video" if is_video else "image",
                "created_at": f.stat().st_mtime,
            })

    # 按创建时间倒序
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return {"items": items}


# ── 健康检查 ──────────────────────────────────────────────────────────────────

@app.post("/ai/analyze", response_model=AnalysisResponse)
async def analyze_result(request: AnalysisRequest):
    if request.target not in {"image", "video", "batch"}:
        raise HTTPException(400, "不支持的解析对象")

    content = _request_deepseek({
        "target": request.target,
        "result": request.result,
    })
    if not content:
        raise HTTPException(502, "DeepSeek 未返回解析内容")

    return AnalysisResponse(content=content)


@app.get("/health")
async def health():
    return {"status": "ok"}
