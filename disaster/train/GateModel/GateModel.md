# 门控模型 (Gating Model)

基于 ResNet-50 的多标签门控/路由模型，用于图片的专家模型调度。给定一张巡检图片，模型决定需要调用哪些下游专家模型来处理它。

## 专家路由配置

| 组     | 下游模型类型   | 覆盖类别                                          |
| ------ | -------------- | ------------------------------------------------- |
| Group1 | 目标检测 (OD)  | snow, water_accumulation, flood                   |
| Group2 | 语义分割 (Seg) | debris_flow, sinkhole, crack, landslide, rockfall |
| Group3 | 语义分割 (Seg) | pipe, construction_area                           |

## 训练命令

### 基础训练

```bash
python train.py
```

### 自定义参数训练

```bash
python train.py \
    --data_dir new_dataset \
    --labels_csv new_dataset/labels.csv \
    --output_dir checkpoints \
    --batch_size 32 \
    --epochs_phase1 10 \
    --epochs_phase2 30 \
    --lr_phase1 1e-3 \
    --lr_phase2 1e-4 \
    --device auto
```

### 参数说明

| 参数            | 默认值                 | 说明                             |
| --------------- | ---------------------- | -------------------------------- |
| --data_dir      | new_dataset            | 数据集目录路径                   |
| --labels_csv    | new_dataset/labels.csv | 标签文件路径                     |
| --output_dir    | checkpoints            | 模型保存目录                     |
| --batch_size    | 32                     | 批次大小                         |
| --epochs_phase1 | 10                     | Phase1 训练轮数（冻结 backbone） |
| --epochs_phase2 | 30                     | Phase2 训练轮数（全模型微调）    |
| --lr_phase1     | 1e-3                   | Phase1 学习率                    |
| --lr_phase2     | 1e-4                   | Phase2 学习率                    |
| --device        | auto                   | 设备选择 (auto/cuda/cpu)         |
| --threshold     | 0.5                    | 分类阈值                         |
| --seed          | 42                     | 随机种子                         |

### 训练策略

- **Phase 1**: 冻结 ResNet-50 backbone，仅训练分类头（warmup）
- **Phase 2**: 解冻 backbone，全模型微调（使用分层学习率）

## 测试命令

训练脚本会自动在测试集上评估模型，无需单独测试命令。训练完成后会输出测试集指标。

如需单独测试，可参考 `train.py` 中的 `validate_epoch` 函数实现。

## 推理命令

### 单张图片推理

```bash
python inference.py --model checkpoints/gating_model_final.pth --image path/to/image.jpg
```

### 批量推理

```bash
python inference.py \
    --model checkpoints/gating_model_final.pth \
    --image_dir path/to/images \
    --output results.json
```

### 交互模式

```bash
python inference.py --model checkpoints/gating_model_final.pth --interactive
```

### 推理参数说明

| 参数          | 默认值 | 说明                 |
| ------------- | ------ | -------------------- |
| --model       | (必填) | 模型权重文件路径     |
| --image       | None   | 单张图片路径         |
| --image_dir   | None   | 图片目录（批量推理） |
| --output      | None   | 批量推理结果输出路径 |
| --threshold   | 0.5    | 分类阈值             |
| --device      | auto   | 设备选择             |
| --batch_size  | 32     | 批量推理批次大小     |
| --interactive | False  | 交互模式开关         |

## 输入输出说明

### 输入

- 格式：RGB 彩色图片（PIL Image 或 3 通道数组）
- 预处理（已封装）：
  - Resize((224, 224)) — 缩放到 224×224
  - ToTensor() — 像素值归一化到 [0, 1]
  - Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]) — ImageNet 标准化

### 输出

模型返回一个字典，结构如下：

```json
{
  "image_path": "path/to/image.jpg",
  "probabilities": {
    "group1_od": 0.9876,
    "group2_seg1": 0.0023,
    "group3_seg2": 0.5001
  },
  "decisions": {
    "group1_od": true,
    "group2_seg1": false,
    "group3_seg2": true
  },
  "routing": [
    {
      "group_id": 0,
      "group_name": "Group1 - OD专家 (目标检测)",
      "task": "object_detection",
      "classes": ["snow", "water_accumulation", "flood"],
      "probability": 0.9876,
      "send_to_expert": true
    }
  ],
  "threshold": 0.5
}
```

## 核心逻辑

这是一个**多标签门控/路由模型**（不是分类模型）。一张图片可以同时属于多个组（`send_to_expert` 可以有多个 `true`）。

## 前后端对接要点

### 加载模型（启动时一次）

```python
from gating_model import GatingModel

checkpoint = torch.load("checkpoints/gating_model_final.pth",
                        map_location=device, weights_only=False)
model = GatingModel(num_groups=3, pretrained=False)
model.load_state_dict(checkpoint["model_state_dict"])
model.eval()
threshold = checkpoint.get("threshold", 0.5)
```

### 处理请求

前端传图片 → 后端做 `Resize(224) + ImageNet normalize` → 调 `model(x)` 拿 logits → sigmoid → threshold → 返回 JSON。

**注意**：`forward()` 只输出原始 logits `(B, 3)`，sigmoid 和 threshold 判断要在业务代码中处理，或直接使用 `model.predict()` 方法。

## 数据格式

### 目录结构

```
new_dataset/
├── images/
│   └── *.jpg (或其他图片格式)
└── labels.csv
```

### 标签文件格式

`labels.csv` 文件包含图片路径和对应的多标签标注：

```csv
image_path,group1_od,group2_seg1,group3_seg2
images/001.jpg,1,0,1
images/002.jpg,0,1,0
images/003.jpg,1,1,0
```

其中：

- `group1_od`：是否属于目标检测组（冰雪、积水、洪水）
- `group2_seg1`：是否属于语义分割组 1（泥石流、塌陷坑、裂缝、滑坡、落石）
- `group3_seg2`：是否属于语义分割组 2（管道、施工区域）

### 数据集分割

训练脚本会自动按比例分割数据集：

- 训练集：70%
- 验证集：15%
- 测试集：15%

## 关键文件说明

| 文件                                 | 说明                                           |
| ------------------------------------ | ---------------------------------------------- |
| `gating_model.py`                    | 模型定义，包含 `forward()` 和 `predict()` 方法 |
| `gating_dataset.py`                  | 数据集类，支持多标签加载和数据增强             |
| `train.py`                           | 两阶段训练脚本，含早停机制                     |
| `inference.py`                       | 推理脚本，支持单张/批量/交互模式               |
| `checkpoints/gating_model_final.pth` | 最终训练好的模型权重                           |
