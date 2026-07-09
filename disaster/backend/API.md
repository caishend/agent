# API 接口文档

**Base URL** `http://localhost:8000`  
**版本** 1.0.0  
**交互文档** `http://localhost:8000/docs`

---

## 目录

- [启动服务](#启动服务)
- [接口概览](#接口概览)
- [POST /predict/image](#post-predictimage)
- [POST /predict/video](#post-predictvideo)
- [GET /download/{filename}](#get-downloadfilename)
- [GET /health](#get-health)
- [数据结构](#数据结构)
- [错误码](#错误码)
- [调用示例](#调用示例)

---

## 启动服务

```bash
# 在项目根目录执行
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

启动时会自动预加载全部模型（GateModel / YOLO / ViTSeg / SegFormer），首次启动需要等待约 10~30 秒，之后每次请求直接推理。

---

## 接口概览

| 方法 | 路径                   | 说明                                    |
| ---- | ---------------------- | --------------------------------------- |
| POST | `/predict/image`       | 上传图片，返回标注图路径和检测/分割结果 |
| POST | `/predict/video`       | 上传视频，返回带标注视频路径和总帧数    |
| GET  | `/download/{filename}` | 下载结果文件（图片或视频）              |
| GET  | `/health`              | 服务健康检查                            |
| GET  | `/files/{filename}`    | 直接访问结果文件（静态资源）            |

---

## POST /predict/image

对单张图片执行完整推理流程（门控路由 → 目标检测 / 语义分割），返回带标注的结果图路径和结构化识别结果。

### 请求

| 参数 | 类型       | 位置      | 必填 | 说明                                                |
| ---- | ---------- | --------- | ---- | --------------------------------------------------- |
| file | UploadFile | form-data | 是   | 图片文件，支持 `.jpg` `.jpeg` `.png` `.bmp` `.webp` |

### 响应

**Content-Type:** `application/json`

```json
{
  "code": 0,
  "msg": "success",
  "image_path": "/files/abc123_result.jpg",
  "gate": {
    "probabilities": {
      "group1_od": 0.92,
      "group2_seg1": 0.07,
      "group3_seg2": 0.11
    },
    "decisions": {
      "group1_od": true,
      "group2_seg1": false,
      "group3_seg2": false
    },
    "threshold": 0.5
  },
  "detections": [
    {
      "class_id": 0,
      "class_name": "snow",
      "confidence": 0.88,
      "box_xyxy": [120.0, 45.0, 380.0, 290.0]
    }
  ],
  "segmentations": []
}
```

### 字段说明

| 字段                          | 类型   | 说明                                             |
| ----------------------------- | ------ | ------------------------------------------------ |
| `code`                        | int    | 0 表示成功，非 0 表示失败                        |
| `msg`                         | string | 状态描述                                         |
| `image_path`                  | string | 带标注结果图的访问路径，可直接拼接 Base URL 访问 |
| `gate.probabilities`          | object | 门控模型对三个专家组的置信概率（0~1）            |
| `gate.decisions`              | object | 是否路由到对应专家（true/false）                 |
| `gate.threshold`              | float  | 本次使用的判决阈值                               |
| `detections`                  | array  | 目标检测结果列表（仅 group1 被激活时有数据）     |
| `detections[].class_id`       | int    | 类别 ID（0=snow, 1=water_accumulation, 2=flood） |
| `detections[].class_name`     | string | 类别名称                                         |
| `detections[].confidence`     | float  | 置信度（0~1）                                    |
| `detections[].box_xyxy`       | array  | 检测框坐标 `[x1, y1, x2, y2]`，像素单位          |
| `segmentations`               | array  | 分割结果列表（group2/group3 被激活时有数据）     |
| `segmentations[].class_name`  | string | 类别名称                                         |
| `segmentations[].pixel_count` | int    | 该类别的像素总数                                 |
| `segmentations[].pixel_ratio` | float  | 该类别占图像总像素的比例（0~1）                  |

### 门控路由说明

| 决策键        | 对应专家           | 识别类别                                          |
| ------------- | ------------------ | ------------------------------------------------- |
| `group1_od`   | YOLO 目标检测      | snow, water_accumulation, flood                   |
| `group2_seg1` | ViTSeg 语义分割    | landslide, crack, rockfall, sinkhole, debris_flow |
| `group3_seg2` | SegFormer 语义分割 | pipe, construction_area                           |

一张图片可以同时路由到多个专家。

### 错误响应

| HTTP 状态码 | 说明           |
| ----------- | -------------- |
| 400         | 文件格式不支持 |
| 500         | 模型推理异常   |

---

## POST /predict/video

对视频逐帧推理，将结果绘制后重新编码输出为 MP4。

### 请求

| 参数 | 类型       | 位置      | 必填 | 说明                                              |
| ---- | ---------- | --------- | ---- | ------------------------------------------------- |
| file | UploadFile | form-data | 是   | 视频文件，支持 `.mp4` `.avi` `.mov` `.mkv` `.wmv` |

> 视频推理耗时较长，帧数越多耗时越长，建议前端展示进度提示。

### 响应

```json
{
  "code": 0,
  "msg": "success",
  "video_path": "/files/abc123_result.mp4",
  "frame_count": 240
}
```

### 字段说明

| 字段          | 类型   | 说明                     |
| ------------- | ------ | ------------------------ |
| `code`        | int    | 0 表示成功               |
| `msg`         | string | 状态描述                 |
| `video_path`  | string | 带标注结果视频的访问路径 |
| `frame_count` | int    | 实际处理的总帧数         |

### 错误响应

| HTTP 状态码 | 说明                                   |
| ----------- | -------------------------------------- |
| 400         | 文件格式不支持                         |
| 500         | 视频处理异常（无法打开文件或推理失败） |

---

## GET /download/{filename}

以附件形式下载结果文件，浏览器会触发保存对话框。

### 请求

| 参数     | 类型   | 位置 | 说明                                                 |
| -------- | ------ | ---- | ---------------------------------------------------- |
| filename | string | path | 文件名，从 `image_path` 或 `video_path` 中取最后一段 |

### 示例

```
GET /download/abc123_result.jpg
GET /download/abc123_result.mp4
```

### 响应

直接返回文件二进制流，`Content-Disposition: attachment`。

### 错误响应

| HTTP 状态码 | 说明       |
| ----------- | ---------- |
| 404         | 文件不存在 |

---

## GET /health

服务健康检查，用于确认服务是否正常运行。

### 响应

```json
{
  "status": "ok"
}
```

---

## 数据结构

### Detection

```json
{
  "class_id": 0,
  "class_name": "snow",
  "confidence": 0.88,
  "box_xyxy": [120.0, 45.0, 380.0, 290.0]
}
```

| 字段         | 类型     | 说明                                        |
| ------------ | -------- | ------------------------------------------- |
| `class_id`   | int      | 类别 ID                                     |
| `class_name` | string   | 类别名称                                    |
| `confidence` | float    | 置信度，范围 0~1                            |
| `box_xyxy`   | float[4] | 检测框左上角和右下角坐标 `[x1, y1, x2, y2]` |

### Segmentation

```json
{
  "class_name": "crack",
  "pixel_count": 12480,
  "pixel_ratio": 0.0487
}
```

| 字段          | 类型   | 说明                        |
| ------------- | ------ | --------------------------- |
| `class_name`  | string | 类别名称（不含 background） |
| `pixel_count` | int    | 该类别的像素总数            |
| `pixel_ratio` | float  | 占图像总像素比例，范围 0~1  |

### GateInfo

```json
{
  "probabilities": {
    "group1_od": 0.92,
    "group2_seg1": 0.07,
    "group3_seg2": 0.11
  },
  "decisions": {
    "group1_od": true,
    "group2_seg1": false,
    "group3_seg2": false
  },
  "threshold": 0.5
}
```

---

## 错误码

| code | 说明                         |
| ---- | ---------------------------- |
| 0    | 成功                         |
| 400  | 请求参数错误（格式不支持等） |
| 404  | 资源不存在                   |
| 500  | 服务器内部错误（推理失败等） |

HTTP 状态码与 `code` 字段保持一致。错误时响应体格式：

```json
{
  "detail": "错误描述信息"
}
```

---

## 调用示例

### Python（requests）

```python
import requests

# 图片推理
with open("test.jpg", "rb") as f:
    resp = requests.post(
        "http://localhost:8000/predict/image",
        files={"file": ("test.jpg", f, "image/jpeg")},
    )
result = resp.json()
print(result["detections"])
print(result["segmentations"])

# 访问结果图
image_url = "http://localhost:8000" + result["image_path"]

# 视频推理
with open("test.mp4", "rb") as f:
    resp = requests.post(
        "http://localhost:8000/predict/video",
        files={"file": ("test.mp4", f, "video/mp4")},
    )
result = resp.json()
print(f"处理帧数: {result['frame_count']}")
video_url = "http://localhost:8000" + result["video_path"]
```

### curl

```bash
# 图片推理
curl -X POST http://localhost:8000/predict/image \
  -F "file=@test.jpg"

# 视频推理
curl -X POST http://localhost:8000/predict/video \
  -F "file=@test.mp4"

# 下载结果
curl -O http://localhost:8000/download/abc123_result.jpg
```

### JavaScript（fetch）

```js
// 图片推理
const form = new FormData();
form.append("file", fileInput.files[0]);

const resp = await fetch("http://localhost:8000/predict/image", {
  method: "POST",
  body: form,
});
const result = await resp.json();

// 直接展示结果图
document.getElementById("result-img").src =
  "http://localhost:8000" + result.image_path;
```

---

## 结果文件访问方式

结果文件存储在服务器的 `backend_output/results/` 目录下，有两种访问方式：

| 方式             | 路径格式                                    | 适用场景                          |
| ---------------- | ------------------------------------------- | --------------------------------- |
| 静态资源直接访问 | `http://localhost:8000/files/{filename}`    | 前端 img src / video src 直接展示 |
| 附件下载         | `http://localhost:8000/download/{filename}` | 触发浏览器下载保存                |

`image_path` 和 `video_path` 字段返回的就是 `/files/...` 格式，拼接 Base URL 即可直接使用。
