# 油气管道灾害智能检测系统（model-pipline）

一套面向油气管道巡检场景的**多模型识别与可视化分析系统**。系统采用「门控路由 + 多专家」的架构：先由门控模型判断图像可能包含哪类灾害，再将其分发给对应的专家模型进行目标检测或语义分割，最后汇总结果并支持 DeepSeek 生成专业分析报告。

支持**图片**、**批量图片**与**视频**三种输入，其中视频支持**逐帧实时推理画面预览**。

## 一、目录结构说明

| 目录 / 文件                  | 作用                                                                                                                                                                                |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`backend/`**               | FastAPI 后端服务。对外提供图片/视频推理、历史记录、AI 解析等 HTTP 接口。详见 [`backend/API.md`](backend/API.md)。                                                                   |
| **`frontend/`**              | Vue 3 + Vuetify 前端单页应用（Vite 构建）。上传素材、展示识别结果、视频实时推理画面、历史记录预览、AI 报告。                                                                        |
| **`pipeline/`**              | **推理主流程**。`pipeline.py` 封装门控 + 三专家的完整推理；`config.py` 集中管理权重路径与推理参数；`run.py` 提供命令行批量推理入口；`experts/` 下是各专家模型的加载/预测/绘制封装。 |
| **`disaster/`**              | ViT-Seg（灾害语义分割）的模型定义与工具代码（`vit_seg/model.py` 等），被 `pipeline` 推理时引用。                                                                                    |
| **`train/`**                 | 各模型的**训练 / 评估脚本与文档**，按模型分子目录：`GateModel/`（门控）、`YOLO/`（YOLO11m）、`vit_seg/`（ViT-Seg）、`SegFormer/`。每个子目录都附带对应的 `*.md` 说明文档。          |
| **`saved_models/`**          | **训练好的模型权重**（不纳入 Git）。`gate/` 门控、`snow/` YOLO、`disaster/` ViT-Seg、`pipe_construction/` SegFormer（HuggingFace 格式目录）。                                       |
| **`snow_group/`**            | YOLO11m 早期训练/测试脚本（已整理进 `train/YOLO/`，此处为历史保留）。                                                                                                               |
| **`pipe_and_construction/`** | SegFormer 早期训练/预测脚本（已整理进 `train/SegFormer/`，此处为历史保留）。                                                                                                        |
| **`backend_output/`**        | 后端运行时产物（不纳入 Git）。`uploads/` 存上传原始文件，`results/` 存标注后的结果图/视频。                                                                                         |
| **`pipeline_output/`**       | `pipeline/run.py` 命令行推理的输出目录（JSON + 可视化图）。                                                                                                                         |
| **`test_images/`**           | 用于本地调试的示例图片与视频。                                                                                                                                                      |
| **`requirements.txt`**       | Python 依赖清单。                                                                                                                                                                   |

> 说明：`saved_models/`、`backend_output/`、`pipeline_output/`、`test_images/`、`frontend/node_modules/`、`frontend/dist/` 等均已在 `.gitignore` 中忽略。模型权重需自行放置到 `saved_models/` 对应子目录（路径见 `pipeline/config.py`）。

---

## 二、环境准备

- Python 3.10 ~ 3.12
- Node.js 18+（前端）
- 可选：NVIDIA GPU + CUDA（加速推理）
- 可选：`ffmpeg`（视频结果转码为浏览器可播放的 H.264，未安装时回退为 mp4v，仍可下载）

### 安装 Python 依赖

```bash
# 建议使用虚拟环境
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

pip install -r requirements.txt
```

> 如需 GPU 版 PyTorch，请先按 https://pytorch.org 选择对应 CUDA 的安装命令，再安装其余依赖。

### 准备模型权重

将训练好的权重放到 `saved_models/` 下（具体文件名见 `pipeline/config.py`）：

```
saved_models/
├── gate/gating_model_final.pth          # 门控模型
├── snow/best.pt                         # YOLO11m
├── disaster/best.pth                    # ViT-Seg 权重
├── disaster/vit_small_patch16_224.pth   # ViT-Seg backbone 预训练权重
└── pipe_construction/                   # SegFormer（HuggingFace 目录）
    ├── config.json
    ├── model.safetensors
    └── preprocessor_config.json
```

---

## 三、启动后端

```bash
# 在项目根目录执行
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：

- 健康检查：http://localhost:8000/health
- 交互式接口文档（Swagger）：http://localhost:8000/docs

> 首次启动会预加载全部模型（门控 + 三专家），稍等片刻直至日志显示 `all models loaded.`。

主要接口（完整说明见 [`backend/API.md`](backend/API.md)）：

| 方法 | 路径                                     | 说明                                                |
| ---- | ---------------------------------------- | --------------------------------------------------- |
| POST | `/predict/image`                         | 单张图片推理                                        |
| POST | `/predict/video`                         | 视频推理（处理完成后返回结果视频）                  |
| POST | `/predict/video/stream`                  | **视频逐帧实时推理**（SSE 流式推送标注画面 + 进度） |
| GET  | `/history`                               | 历史识别记录（原图/结果配对）                       |
| POST | `/ai/analyze`                            | 调用 DeepSeek 生成结果解析报告                      |
| GET  | `/files/*`、`/original/*`、`/download/*` | 结果文件 / 原始文件访问与下载                       |

---

## 四、启动前端

```bash
cd frontend
npm install        # 首次需安装依赖
npm run dev        # 开发模式，默认 http://localhost:3000
```

- 开发服务器默认端口 **3000**，并通过 Vite 代理把 `/predict`、`/history`、`/files`、`/ai` 等请求转发到后端 `http://localhost:8000`（配置见 `frontend/vite.config.js`）。因此**请先启动后端再启动前端**。
- 默认登录账号 / 密码：`123` / `123`（演示用，见 `frontend/src/App.vue`）。

构建生产包：

```bash
cd frontend
npm run build      # 产物输出到 frontend/dist/
npm run preview    # 本地预览生产包
```

---

## 五、命令行批量推理（不经过 Web）

`pipeline/run.py` 提供脱离前后端的本地推理入口：

```bash
# 单张图片，保存可视化结果
python -m pipeline.run --image test_images/img_000004.jpg --save-vis

# 批量目录推理，输出 JSON 与可视化
python -m pipeline.run --image-dir test_images/ --output-dir pipeline_output/ --save-vis

# 可选参数
#   --device cuda|cpu|auto      指定推理设备
#   --gate-threshold 0.5        门控 sigmoid 阈值
```

结果（JSON + 各专家可视化图）会写入 `--output-dir`（默认 `pipeline_output/`）。

---

## 六、模型训练

各模型的训练 / 评估脚本与说明集中在 `train/` 下，按模型查阅对应文档：

- 门控模型：[`train/GateModel/GateModel.md`](train/GateModel/GateModel.md)
- YOLO11m 目标检测：[`train/YOLO/YOLO.md`](train/YOLO/YOLO.md)
- ViT-Seg 语义分割：[`train/vit_seg/ViT-Seg.md`](train/vit_seg/ViT-Seg.md)
- SegFormer 语义分割：[`train/SegFormer/SegFormer.md`](train/SegFormer/SegFormer.md)

---

## 七、常见问题

- **视频结果无法在浏览器预览**：未安装 `ffmpeg` 时输出为 mp4v 编码，部分浏览器不支持在线播放，可点击下载查看；安装 `ffmpeg` 并加入 PATH 后会自动转码为 H.264。
- **AI 解析失败**：`/ai/analyze` 依赖 DeepSeek API，请确认 `backend/main.py` 中的 `DEEPSEEK_API_KEY` 有效且网络可达。
- **模型加载报错 / 找不到权重**：检查 `saved_models/` 下文件是否齐全，路径以 `pipeline/config.py` 中的 `WEIGHTS` 为准。
