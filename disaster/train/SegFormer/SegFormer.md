# SegFormer：基于 Transformer 的管道与施工区域语义分割

## 任务概述

对管道巡检图像进行**逐像素 3 分类语义分割**：

| ID  | 类别     | 英文                | 说明       |
| :-: | :------- | :------------------ | :--------- |
|  0  | 背景     | `background`        | 非目标区域 |
|  1  | 管道     | `pipe`              | 油气管道   |
|  2  | 施工区域 | `construction_area` | 施工场地   |

## 模型架构

使用 HuggingFace `transformers` 库中的 **SegFormer MIT-B3** 预训练模型：

- 编码器：MiT-B3 (Mix Vision Transformer)
- 解码器：MLP 头
- 预训练权重：`nvidia/mit-b3`

## 训练命令

### 基础训练

```bash
python train_segformer.py
```

### 自定义参数训练

```bash
python train_segformer.py \
    --data-dir path/to/dataset \
    --output-dir runs/segformer_experiment \
    --model-name nvidia/mit-b3 \
    --image-size 768 \
    --epochs 50 \
    --batch-size 2 \
    --gradient-accumulation-steps 2 \
    --lr 6e-5 \
    --weight-decay 0.01 \
    --device cuda
```

### 参数说明

| 参数                          | 默认值                                                          | 说明                     |
| ----------------------------- | --------------------------------------------------------------- | ------------------------ |
| --data-dir                    | `D:\zhinengruanjianlingyu2\mergedata`                           | 数据集目录               |
| --output-dir                  | `D:\zhinengruanjianlingyu2\runs\segformer_mit_b3_letterbox_768` | 输出目录                 |
| --model-name                  | `nvidia/mit-b3`                                                 | 预训练模型名称           |
| --image-size                  | 768                                                             | 输入图像尺寸             |
| --epochs                      | 50                                                              | 训练轮数                 |
| --batch-size                  | 2                                                               | 批次大小                 |
| --gradient-accumulation-steps | 2                                                               | 梯度累积步数             |
| --lr                          | 6e-5                                                            | 学习率                   |
| --weight-decay                | 0.01                                                            | 权重衰减                 |
| --eval-every                  | 1                                                               | 每 N 轮评估一次          |
| --num-workers                 | 0                                                               | 数据加载线程数           |
| --resume                      | False                                                           | 是否从断点续训           |
| --offline                     | True                                                            | 离线模式（使用本地缓存） |
| --cpu                         | False                                                           | 是否使用 CPU             |
| --no-amp                      | False                                                           | 禁用混合精度训练         |

## 测试命令

### 最佳模型测试

```bash
python test_best_segformer.py
```

### 自定义测试参数

```bash
python test_best_segformer.py \
    --data-dir path/to/dataset \
    --checkpoint runs/segformer_experiment/best \
    --output-dir runs/segformer_experiment/test_best \
    --split test \
    --image-size 768 \
    --batch-size 2 \
    --max-visualizations 50
```

### 测试参数说明

| 参数                 | 默认值                                                                    | 说明           |
| -------------------- | ------------------------------------------------------------------------- | -------------- |
| --data-dir           | `D:\zhinengruanjianlingyu2\mergedata`                                     | 数据集目录     |
| --checkpoint         | `D:\zhinengruanjianlingyu2\runs\segformer_mit_b3_letterbox_768\best`      | 模型权重目录   |
| --output-dir         | `D:\zhinengruanjianlingyu2\runs\segformer_mit_b3_letterbox_768\test_best` | 测试输出目录   |
| --split              | test                                                                      | 测试集名称     |
| --image-size         | 768                                                                       | 输入图像尺寸   |
| --batch-size         | 2                                                                         | 批次大小       |
| --max-visualizations | 50                                                                        | 最大可视化数量 |

## 外部数据推理

```bash
python predict_outerdata.py \
    --input-dir path/to/outer/images \
    --output-dir path/to/output \
    --run-dir runs/segformer_experiment \
    --image-size 512 \
    --save-mask \
    --save-overlay
```

### 推理参数说明

| 参数           | 默认值                                            | 说明                     |
| -------------- | ------------------------------------------------- | ------------------------ |
| --input-dir    | `D:\zhinengruanjianlingyu2\outerdata`             | 输入图像目录             |
| --output-dir   | 同 input-dir                                      | 输出目录                 |
| --run-dir      | `D:\zhinengruanjianlingyu2\runs\segformer_mit_b3` | 训练运行目录             |
| --checkpoint   | None                                              | 直接指定 checkpoint 路径 |
| --image-size   | 512                                               | 推理图像尺寸             |
| --save-mask    | False                                             | 保存预测掩码             |
| --save-overlay | False                                             | 保存叠加图               |

## 数据格式

### 目录结构

```
dataset/
├── train/
│   ├── images/
│   │   └── *.jpg
│   └── masks/
│       └── *mask.png
├── valid/
│   ├── images/
│   └── masks/
└── test/
    ├── images/
    └── masks/
```

### 标签格式

掩码图像为单通道灰度图，像素值对应类别 ID：

- 0: 背景
- 1: 管道
- 2: 施工区域

## 评估指标

| 指标            | 说明           |
| --------------- | -------------- |
| pixel_acc       | 像素准确率     |
| miou            | 平均 IoU       |
| foreground_miou | 前景类平均 IoU |
| mean_precision  | 平均精确率     |
| mean_recall     | 平均召回率     |

## 关键文件说明

| 文件                     | 说明                             |
| ------------------------ | -------------------------------- |
| `train_segformer.py`     | 训练脚本，支持断点续训和混合精度 |
| `test_best_segformer.py` | 最佳模型测试脚本，生成可视化结果 |
| `predict_outerdata.py`   | 外部数据推理脚本                 |
| `merge_datasets.py`      | 数据集合并工具                   |
| `output/best/`           | 最佳模型权重（HuggingFace 格式） |
| `output/last/`           | 最后一轮模型权重                 |
| `output/metrics.csv`     | 训练指标记录                     |
| `output/visualizations/` | 测试可视化结果                   |

## 前后端对接要点

### 加载模型

```python
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

processor = SegformerImageProcessor.from_pretrained("path/to/checkpoint")
model = SegformerForSemanticSegmentation.from_pretrained("path/to/checkpoint")
model.eval()
```

### 推理流程

1. 图像预处理：letterbox resize 到指定尺寸
2. 使用 `processor` 处理图像
3. 调用 `model(pixel_values)` 获取 logits
4. 上采样 logits 到原图尺寸
5. argmax 获取预测类别

### 输出格式

```python
# 模型返回
outputs = model(pixel_values=pixel_values)
logits = outputs.logits  # (B, num_classes, H, W)
preds = logits.argmax(dim=1)  # (B, H, W)
```

## 注意事项

1. 训练和测试使用相同的 `--image-size` 参数
2. 数据集目录需包含 train/valid/test 三个子目录
3. 离线模式需要提前下载 HuggingFace 模型权重到本地缓存
4. 建议使用 GPU 进行训练，批处理大小受显存限制
