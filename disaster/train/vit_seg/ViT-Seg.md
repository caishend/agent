# ViTSeg：基于 Vision Transformer 的地质灾害语义分割

**ViTSeg** 是一个轻量级语义分割模型，结合了 **ViT-Small** 编码器与**渐进式 UNet 风格解码器**，用于对航拍及野外图像中的地质灾害进行逐像素分类。

> **最佳验证 mIoU: 0.7150 &nbsp;|&nbsp; 测试 mIoU: 0.7111 &nbsp;|&nbsp; 参数量: 25.5M &nbsp;|&nbsp; 6 分类分割**

---

## 目录

- [任务概述](#任务概述)
- [模型架构](#模型架构)
- [关键设计决策](#关键设计决策)
- [实验结果](#实验结果)
- [项目结构](#项目结构)
- [环境安装](#环境安装)
- [使用方法](#使用方法)
- [训练配置](#训练配置)
- [改进方向](#改进方向)
- [关键数据速查](#关键数据速查)
- [参考文献](#参考文献)

---

## 任务概述

对地质灾害图像进行**逐像素 6 分类语义分割**：

| ID  | 类别   | 英文          | 视觉特征                                          |
| :-: | :----- | :------------ | :------------------------------------------------ |
|  0  | 滑坡   | `landslide`   | 舌状或不规则土体斑块，纹理粗糙                    |
|  1  | 裂缝   | `crack`       | 细长线性结构，宽度仅 1–3 像素                     |
|  2  | 落石   | `rockfall`    | 散布块状岩石，大小不一，与背景裸岩易混淆          |
|  3  | 塌陷坑 | `sinkhole`    | 近圆形凹陷，边缘较清晰                            |
|  4  | 泥石流 | `debris_flow` | 扇状堆积体，与滑坡存在类间相似性                  |
|  5  | 背景   | `background`  | 正常地面、植被、天空等非灾害区域（约占 83% 像素） |

### 核心难点

- **极端类别不平衡**：背景像素是滑坡的 **213 倍**
- **类间混淆**：滑坡 ↔ 泥石流（纹理相似）、落石 ↔ 背景（裸岩相似）
- **小目标检测**：裂缝仅 1–3 像素宽，在 512×512 分辨率下信息严重不足
- **跨源泛化**：数据来自多个地理区域和不同采集设备

### 评估指标

| 指标                         | 角色                   | 说明                               |
| :--------------------------- | :--------------------- | :--------------------------------- |
| **mIoU**（主指标）           | 6 类 Macro-average IoU | 对类别不平衡鲁棒，反映真实分割质量 |
| **Dice Coefficient**（辅助） | 6 类 Macro-average F1  | 与 IoU 高度相关，额外验证          |
| Pixel Accuracy（参考）       | 全局像素正确率         | 受背景主导，不作为决策依据         |

### 数据格式

#### 目录结构

数据集需放置在项目根目录下的 `merged_five_clean/` 目录：

```
merged_five_clean/
├── train/
│   ├── images/
│   │   └── *.png (或其他图片格式)
│   └── masks/
│       └── *.png
├── val/
│   ├── images/
│   └── masks/
└── test/
    ├── images/
    └── masks/
```

#### 标签格式

掩码图像为单通道灰度图，像素值对应类别 ID：

| ID  | 类别   | 英文          |
| :-: | :----- | :------------ |
|  0  | 滑坡   | `landslide`   |
|  1  | 裂缝   | `crack`       |
|  2  | 落石   | `rockfall`    |
|  3  | 塌陷坑 | `sinkhole`    |
|  4  | 泥石流 | `debris_flow` |
|  5  | 背景   | `background`  |

#### 数据集准备

运行 Source-Level 分割脚本（仅需一次）：

```bash
python split_dataset.py
```

该脚本会按采集来源进行数据分割，确保同一场景的连续帧不会同时出现在训练集和测试集中，避免数据泄露导致的指标虚高。

---

## 模型架构

```
输入 (512×512×3)
    │
    ▼
┌─────────────────────────────────────────┐
│  Patch Embedding (Conv2d 16×16)         │
│  → 1024 个 patch token，每个 384 维     │
│  → 32×32 空间网格                       │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│  ViT-Small 编码器 (ImageNet-21k 预训练)  │
│  · 12 层 Transformer                    │
│  · embed_dim=384, num_heads=6           │
│  · MLP ratio=4                          │
│  · 学习率=1e-4（差异化，较低）            │
└─────────────────────────────────────────┘
    │  (B, 1025, 384) — 含 [CLS] token
    ▼
┌──────────────────┐   ┌──────────────────┐
│  丢弃 [CLS]      │ → │  Reshape         │
│  1025→1024 token │   │  → (B,384,32,32) │
└──────────────────┘   └──────────────────┘
    │
    ▼
┌──────────────────────────────────────────┐
│  渐进式解码器 (学习率=5e-4，较高)          │
│  Dec4: 384→256  (32×32 → 64×64)         │
│  Dec3: 256→128  (64×64 → 128×128)       │
│  Dec2: 128→64   (128×128 → 256×256)     │
│  Dec1: 64→32    (256×256 → 512×512)     │
│  每层: Conv3×3+BN+ReLU ×2 + 2×上采样    │
└──────────────────────────────────────────┘
    │
    ▼
┌──────────────────┐
│  Conv1×1 输出头  │  32 → 6 类
└──────────────────┘
    │
    ▼
输出 (512×512×6) logits
```

### 为什么选择 ViT + UNet 解码器？

| 候选方案           | 优势                        | 劣势                           | 结论               |
| :----------------- | :-------------------------- | :----------------------------- | :----------------- |
| U-Net (CNN)        | Skip Connection 保留细节    | 感受野有限，全局语义弱         | 不适合复杂自然场景 |
| DeepLabV3+         | ASPP 多尺度上下文           | ResNet101 59M 参数过重         | 性价比低           |
| SegFormer (MiT-B2) | 层次化 Transformer + MLP 头 | 依赖 HuggingFace，离线部署不便 | 优秀的替代方案     |
| **ViTSeg** ✅      | 全局自注意力 + 轻量解码器   | 无层次特征，无 Skip Connection | **本项目选择**     |

**选择理由**：

1. 地质灾害（滑坡、泥石流）通常覆盖大面积连续区域，ViT 自注意力天然捕获长距离依赖
2. ViT-Small 仅 25.5M 参数，远轻于 DeepLabV3+ (59M)，与 SegFormer (24.7M) 相当
3. `timm` + 本地 `.pth` 推理，无需联网下载 HuggingFace 权重，离线部署友好
4. ViT + UNet 解码器的组合是语义分割的前沿方向，具有学术研究价值

---

## 关键设计决策

### 1. 无 Skip Connection

ViT 输出的是**单一尺度**的 patch token（32×32），没有 CNN 那样的层次化特征图（64×64、128×128…）。因此传统的 U-Net Skip Connection 无法直接使用，解码器采用**纯渐进式上采样**。

> 代价：边界细节不如带 Skip Connection 的 CNN U-Net。但 ViT 的全局自注意力部分弥补了细节定位能力。

### 2. 位置编码自适应

预训练 ViT 的位置编码针对 224×224（14×14 grid）。本项目使用 512×512 输入（32×32 grid），通过 `timm.resize_pos_embed` 进行双线性插值，无需重新训练。

```python
# model.py 核心代码
if state["pos_embed"].shape != self.encoder.pos_embed.shape:
    state["pos_embed"] = resize_pos_embed(
        state["pos_embed"], self.encoder.pos_embed,
        num_prefix_tokens=1,
        gs_new=(self.grid_size, self.grid_size),  # (32, 32)
    )
```

### 3. 差异化学习率

| 组件            | 初始化方式          |   学习率   | 原因                       |
| :-------------- | :------------------ | :--------: | :------------------------- |
| ViT 编码器      | ImageNet-21k 预训练 | **1×10⁻⁴** | 保留预训练知识，微调为主   |
| 解码器 + 输出头 | Kaiming 随机初始化  | **5×10⁻⁴** | 需要更快收敛，从头学习分割 |

```python
def param_groups(self, lr_backbone, lr_head):
    return [
        {"params": self.encoder.parameters(), "lr": lr_backbone},  # 1e-4
        {"params": self.decoder_params(),     "lr": lr_head},      # 5e-4
    ]
```

### 4. 混合损失函数

$$\mathcal{L} = 0.5 \cdot \mathcal{L}_{\text{CE}} + 0.5 \cdot \mathcal{L}_{\text{Dice}}$$

- **CE Loss**（`CrossEntropyLoss`，不加类别权重）：逐像素监督，梯度稳定
- **Dice Loss**（6 类 Macro-average）：对类别不平衡天然鲁棒，直接优化区域重叠

> **为什么不给 CE Loss 加类别权重？** 加权重后背景类（占比 83%）的权重极小（~0.05），会导致背景分割质量严重下降——而背景分割不好会直接污染前景类的边界。混合 Dice Loss + Macro mIoU 评估比加权 CE Loss 更有效。

### 5. Source-Level 数据分割

同一场景的连续帧若随机分割，会同时进入 train 和 test，严重高估泛化性能。本项目按**采集来源**进行分割：

- 从文件名提取 `(类别, 来源ID)` — 如 `landslide__hz010.png` → `('landslide', 'hz')`
- 每个来源作为一个不可分割的单元
- 贪心分配到 train/val/test，目标比例 70/15/15
- **验证零跨 split 来源泄露** — 确保评估反映真实泛化能力

---

## 实验结果

### 测试集评估（最佳模型，epoch 13）

```
mIoU     : 0.7111
Dice     : 0.8092
Pixel Acc: 0.9576
Loss     : 0.4399
```

### 逐类 IoU

| 类别        |    IoU     | 评级  | 分析                                                     |
| :---------- | :--------: | :---: | :------------------------------------------------------- |
| Background  |   0.9531   | ★★★★★ | 背景占据大量区域，特征差异大，极易识别                   |
| Sinkhole    |   0.8591   | ★★★★☆ | 前景类中表现最好——圆形 + 阴影特征明显                    |
| Rockfall    |   0.7900   | ★★★★☆ | 出乎意料的好——模型能较好区分落石与裸岩背景               |
| Debris Flow |   0.7231   | ★★★☆☆ | 中等，与 Landslide 存在类间混淆                          |
| Landslide   |   0.6622   | ★★★☆☆ | 可接受，但边界模糊区域常被误分为 Debris Flow             |
| Crack       | **0.2790** | ★☆☆☆☆ | **最大瓶颈**——裂缝仅 1–3 px 宽，512 分辨率下信息严重不足 |

### 验证集 vs 测试集

| 指标 | Val (epoch 13) | Test   | 差异       |
| :--- | :------------- | :----- | :--------- |
| mIoU | 0.7150         | 0.7111 | −0.0039 ✅ |
| Dice | 0.8184         | 0.8092 | −0.0092    |
| Loss | 0.4276         | 0.4399 | +0.0123    |

> **Val/Test 差距仅 0.004 mIoU**，验证了 Source-Level Split 的有效性——模型在未见过的采集源上泛化良好，不存在数据泄露导致的指标虚高。

### 分阶段训练分析

| 阶段         | Epoch | Train Loss  | Val Loss    | Train IoU   | Val IoU            | 说明                                   |
| :----------- | :---- | :---------- | :---------- | :---------- | :----------------- | :------------------------------------- |
| **Warmup**   | 1–5   | 0.907→0.212 | 0.864→0.507 | 0.483→0.773 | 0.578→0.623        | LR 从零增长，模型快速学习粗粒度特征    |
| **快速收敛** | 6–9   | 0.175→0.098 | 0.482→0.435 | 0.781→0.850 | 0.633→0.703        | Cosine LR 处于高位，IoU 快速提升至 0.7 |
| **峰值区域** | 10–13 | 0.092→0.085 | 0.437→0.428 | 0.859→0.866 | 0.707→**0.715** ⭐ | epoch 13 达到最佳 Val mIoU             |
| **过拟合**   | 14–18 | 0.078→0.067 | 0.435→0.443 | 0.877→0.893 | 0.712→0.711        | Val Loss 上升停滞，Train 继续优化      |

- **最佳 epoch**: 13（Val mIoU = 0.7150）
- **过拟合起始点**: Epoch 9+（Val Loss 停止下降）
- **早停**: 未触发（patience=20，训练在 epoch 18 停止）

---

## 环境安装

### 依赖

```
Python >= 3.8
PyTorch >= 2.0
timm >= 0.9
numpy, matplotlib, Pillow, tqdm
```

### 安装步骤

```bash
# 克隆仓库
git clone <repo-url>
cd 专家

# 安装依赖
pip install torch torchvision timm numpy matplotlib Pillow tqdm

# 下载 ViT-Small 预训练权重（可选——timm 可自动下载）
# 将 vit_small_patch16_224.pth 放置到 vit_seg/pretrained/ 目录下
```

---

## 使用方法

### 1. 数据准备

```bash
# 运行 Source-Level 分割（仅需一次，防止数据泄露）
python split_dataset.py
# 输出: merged_five_clean/  (train/val/test，零跨来源泄露)
```

### 2. 训练

```bash
# 从头开始训练
python vit_seg/train.py

# 从 checkpoint 断点续训
python vit_seg/train.py --resume vit_seg/outputs/checkpoints/last.pth

# 自定义参数训练
python vit_seg/train.py --epochs 100 --batch_size 8 --device cuda
```

### 3. 评估

```bash
# 在测试集上快速评估（CPU）
python vit_seg/eval_quick.py --device cpu

# 使用指定 checkpoint 评估
python vit_seg/eval_quick.py --checkpoint vit_seg/outputs/checkpoints/best.pth --device cuda
```

### 4. 推理

```bash
# 对目录下所有图像进行批量推理
python vit_seg/test.py --test_dir path/to/images --output_dir path/to/results
```

---

## 训练配置

| 超参数          | 值                                  | 说明                  |
| :-------------- | :---------------------------------- | :-------------------- |
| 优化器          | AdamW                               | weight_decay=1×10⁻²   |
| Backbone 学习率 | 1×10⁻⁴                              | ViT-Small 预训练权重  |
| Head 学习率     | 5×10⁻⁴                              | 解码器随机初始化      |
| 学习率调度      | Warmup (5 epoch) + Cosine Annealing | η_min=1×10⁻⁶          |
| Batch Size      | 8                                   | 受限于 512×512 分辨率 |
| 输入分辨率      | 512×512                             | 对应 32×32 patch grid |
| 梯度裁剪        | max_norm=1.0                        | 防止梯度爆炸          |
| 实际训练轮数    | 18（最大设 100）                    | 早停 patience=20      |
| 损失函数        | 0.5×CE + 0.5×Dice                   | 无类别权重            |

---

## 改进方向

### 训练层面

- [ ] **延长训练**：当前仅 18 epochs，Cosine LR 远未到底部 (1e-6)，模型有继续提升空间
- [ ] **更大 Batch Size**：8 → 16/32，降低梯度噪声，提升收敛稳定性
- [ ] **更强的正则化**：weight_decay 1e-2 → 5e-2；对 ViT 层应用 DropPath / Stochastic Depth

### 数据层面

- [ ] **类别平衡采样**：使用 WeightedRandomSampler，确保每 batch 中各前景类均出现
- [ ] **裂缝高分辨率处理**：裂缝仅 1–3 像素宽 → 滑动窗口或 1024×1024 输入
- [ ] **落石数据扩充**：Val+Test 仅 16 张，需要更多独立源的数据
- [ ] **Copy-Paste 增强**：将小类（landslide/crack）语义区域粘贴到不同背景中

### 模型层面

- [ ] **多尺度特征提取**：从 ViT 中间层提取多层 token → 构建层次化解码器（参考 SegFormer）
- [ ] **边界损失**：添加 Boundary Loss，专门优化裂缝/落石边界
- [ ] **辅助 CNN 分支**：并联轻量 CNN 提供局部细节特征，与 ViT 全局特征融合

### 系统层面

- [ ] **领域预训练**：在灾害数据集上做 MoCo/SimCLR 域内对比学习预训练
- [ ] **多模态融合**：融合 DEM（高程）、坡度图等地形数据
- [ ] **半监督学习**：利用大量未标注的灾害区域图像

---

## 关键数据速查

| 指标               | 值                                           |
| :----------------- | :------------------------------------------- |
| 总图像数           | 3,956（Train: 3,384 / Val: 287 / Test: 285） |
| 输入分辨率         | 512×512                                      |
| 模型参数量         | 25.5M（ViT-Small + 解码器）                  |
| 训练轮数           | 18 epochs                                    |
| **最佳 Val mIoU**  | **0.7150** @ Epoch 13                        |
| **Test mIoU**      | **0.7111**（285 张图像）                     |
| Val–Test mIoU 差距 | 0.0039                                       |
| 背景像素占比       | 83.2%                                        |
| 最严重不平衡比     | bg:landslide = 213:1                         |

---

## 参考文献

1. Dosovitskiy et al. "An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale." _ICLR 2021_.
2. Xie et al. "SegFormer: Simple and Efficient Design for Semantic Segmentation with Transformers." _NeurIPS 2021_.
3. Ronneberger et al. "U-Net: Convolutional Networks for Biomedical Image Segmentation." _MICCAI 2015_.
4. Milletari et al. "V-Net: Fully Convolutional Neural Networks for Volumetric Medical Image Segmentation." _3DV 2016_.（Dice Loss）
5. Loshchilov & Hutter. "SGDR: Stochastic Gradient Descent with Warm Restarts." _ICLR 2017_.（Cosine Annealing）

---

_详细的方法论、训练曲线和逐类分析见 [ViTSeg_Detailed_Report.md](ViTSeg_Detailed_Report.md)。_
