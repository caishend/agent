# YOLO11m：基于 YOLO 的冰雪与积水目标检测

## 任务概述

对灾害巡检图像进行**目标检测**，识别三类目标：

| ID  | 类别 | 英文                 | 说明             |
| :-: | :--- | :------------------- | :--------------- |
|  0  | 冰雪 | `snow`               | 道路冰雪覆盖区域 |
|  1  | 积水 | `water_accumulation` | 路面积水区域     |
|  2  | 洪水 | `flood`              | 洪涝灾害区域     |

## 模型架构

使用 Ultralytics **YOLO11m** 目标检测模型：

- 骨干网络：YOLO11 Backbone
- 颈部结构：PAN-FPN
- 检测头：YOLO Head
- 预训练权重：`yolo11m.pt`

## 训练命令

### 基础训练

```bash
python train_yolo11m_full_balanced.py
```

### 参数说明（在代码中修改）

| 参数          | 默认值 | 说明            |
| ------------- | ------ | --------------- |
| EPOCHS        | 100    | 训练轮数        |
| IMGSZ         | 768    | 输入图像尺寸    |
| BATCH         | 4      | 批次大小        |
| DEVICE        | 0      | GPU 设备 ID     |
| WORKERS       | 4      | 数据加载线程数  |
| PATIENCE      | 30     | 早停耐心值      |
| LR0           | 0.003  | 初始学习率      |
| LRF           | 0.01   | 最终学习率      |
| WARMUP_EPOCHS | 5      | 热身轮数        |
| MOSAIC        | 0.8    | Mosaic 增强概率 |
| MIXUP         | 0.05   | Mixup 增强概率  |

## 数据平衡策略

训练脚本自动构建平衡训练列表，通过重复采样少数类图像实现类别平衡：

| 类别               | 对象乘数 | 说明                 |
| ------------------ | -------- | -------------------- |
| snow               | 1.70     | 召回率较低，需要增强 |
| water_accumulation | 1.70     | 需要更强召回         |
| flood              | 1.25     | 已相对较强           |

## 测试命令

### 最佳模型测试

```bash
python test_best_yolo11m.py
```

### 测试参数说明（在代码中修改）

| 参数  | 默认值 | 说明         |
| ----- | ------ | ------------ |
| IMGSZ | 768    | 推理图像尺寸 |
| BATCH | 4      | 批次大小     |
| CONF  | 0.25   | 置信度阈值   |
| IOU   | 0.70   | NMS IoU 阈值 |

## 置信度阈值扫描

```bash
python eval_yolo11m_current.py
```

该脚本在多个置信度阈值上评估模型，帮助选择最优阈值：

- 默认扫描范围：`[0.001, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]`
- 目标指标：Precision >= 0.90, Recall >= 0.85

## 数据格式

### 目录结构

```
dataset/
├── train/
│   ├── images/
│   │   └── *.jpg
│   └── labels/
│       └── *.txt
├── valid/
│   ├── images/
│   └── labels/
└── test/
    ├── images/
    └── labels/
```

### 标签格式（YOLO 格式）

```
<class_id> <x_center> <y_center> <width> <height>
```

坐标为归一化值（相对于图像尺寸）。

## 评估指标

| 指标      | 说明                  |
| --------- | --------------------- |
| Precision | 精确率                |
| Recall    | 召回率                |
| mAP50     | IoU=0.5 时的 mAP      |
| mAP50-95  | IoU=0.5~0.95 时的 mAP |

## 关键文件说明

| 文件                             | 说明                     |
| -------------------------------- | ------------------------ |
| `train_yolo11m_full_balanced.py` | 训练脚本，含数据平衡策略 |
| `test_best_yolo11m.py`           | 最佳模型测试脚本         |
| `eval_yolo11m_current.py`        | 置信度阈值扫描评估脚本   |
| `weights/best.pt`                | 最佳模型权重             |
| `weights/last.pt`                | 最后一轮模型权重         |
| `results.csv`                    | 训练指标记录             |
| `data_full_balanced.yaml`        | 训练数据配置文件         |

## 前后端对接要点

### 加载模型

```python
from ultralytics import YOLO

model = YOLO("path/to/best.pt")
model.eval()
```

### 推理流程

```python
results = model.predict(
    source="path/to/image.jpg",
    imgsz=768,
    conf=0.25,
    iou=0.70,
    device="cuda",
)
```

### 输出格式

```python
# 检测结果结构
result = results[0]
boxes = result.boxes  # 边界框信息
boxes.xyxy  # 边界框坐标 (x1, y1, x2, y2)
boxes.cls   # 类别 ID
boxes.conf  # 置信度
```

## 注意事项

1. 训练数据需要按 YOLO 格式组织
2. 建议使用 GPU 进行训练和推理
3. 置信度阈值需要根据实际场景调整
4. 数据平衡策略会自动生成 `train_balanced.txt` 文件
5. 训练脚本会自动在验证集和测试集上评估
