# SkyGuard：基于 Graph RAG 与任务记忆增强的多模态遥感灾害智能分析 Agent

> **SkyGuard: A Task-Memory Enhanced Multimodal Disaster Intelligence Agent with Graph RAG**

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统目标](#2-系统目标)
3. [系统总体架构](#3-系统总体架构)
4. [Agent 核心设计](#4-agent-核心设计)
5. [工具模块详细设计](#5-工具模块详细设计)
6. [数据库设计](#6-数据库设计)
7. [接口设计](#7-接口设计)
8. [用例与流程图](#8-用例与流程图)
9. [技术栈](#9-技术栈)
10. [开发计划](#10-开发计划)
11. [部署架构](#11-部署架构)
12. [项目创新点](#12-项目创新点)

---

## 1. 项目概述

### 1.1 项目背景

灾害分析场景中，相关人员需要综合处理以下多源异构信息：

- 历史灾害案例与知识库
- 用户上传的灾害报告与文档
- 卫星遥感影像
- 实时新闻与气象预警
- 政府应急公告

传统灾害分析方式面临以下核心痛点：

| 痛点 | 描述 |
|------|------|
| 数据分散 | 信息来源多样，人工整合成本极高 |
| 依赖专家 | 灾害研判强依赖专家经验，难以标准化 |
| 时效性差 | 信息更新不及时，决策滞后 |
| 报告耗时 | 灾害评估报告编制周期长 |

### 1.2 项目定位

本项目设计一个**灾害智能 Agent 系统**，以灾害任务为中心，Agent 通过任务记忆管理用户上下文，自动调用 Graph RAG、文档理解、遥感分析、浏览器检索等工具，融合多源信息完成灾害评估、应急决策与报告生成。

**核心工作流：**

```
灾害信息采集 → 多源数据融合 → 灾害影响分析 → 风险评估 → 应急方案制定 → 报告生成 → 自动通知
```

### 1.3 面向用户

- 应急管理人员
- 灾害分析研究人员
- 科研机构人员

---

## 2. 系统目标

### 2.1 任务级智能交互

用户创建灾害任务后，Agent 持续维护该任务的完整上下文：

- 历史对话记录
- 用户上传资料摘要
- 各阶段分析结果
- 网络检索证据链

### 2.2 自主工具调用

Agent 根据用户意图自动规划并调用工具：

- Graph RAG 知识推理
- 文档解析与理解
- 遥感影像分析
- 浏览器实时检索
- 风险评估与报告生成

### 2.3 多模态灾害感知

| 模态 | 数据类型 |
|------|---------|
| 文本 | 灾害报告、新闻公告、气象预警 |
| 图像 | 卫星遥感影像（PNG/TIF） |
| 结构化 | 历史灾害知识图谱 |

---

## 3. 系统总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         用户 (Web)                           │
└─────────────────────────┬───────────────────────────────────┘
                          │  HTTP / WebSocket
┌─────────────────────────▼───────────────────────────────────┐
│                    Web 交互平台 (Vue3)                        │
│          任务管理 · 对话界面 · 文件上传 · 结果展示             │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                   Disaster Agent Core                        │
│   ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│   │ 意图识别模块 │  │ 任务规划模块  │  │   记忆管理模块     │  │
│   └─────────────┘  └──────────────┘  └───────────────────┘  │
│                  Function Calling Dispatcher                  │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────┘
       │          │          │          │          │
  ┌────▼───┐ ┌───▼───┐ ┌────▼────┐ ┌───▼───┐ ┌───▼────┐
  │GraphRAG│ │ Doc   │ │ Remote  │ │Browse │ │ Report │
  │  Tool  │ │ Tool  │ │Sensing  │ │ Tool  │ │  Tool  │
  └────┬───┘ └───┬───┘ └────┬────┘ └───┬───┘ └───┬────┘
       │         │           │          │          │
┌──────▼─────────▼───────────▼──────────▼──────────▼──────────┐
│                         数据存储层                            │
│        MySQL · Neo4j · Vector DB · 本地文件系统               │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Agent 核心设计

### 4.1 控制流程

以用户输入"分析四川某地区洪水风险，并生成报告"为例：

**Step 1：意图识别**

```
输入: "分析四川某地区洪水风险，并生成报告"
输出:
  任务类型: 灾害风险评估
  目标动作: 生成报告
  灾害类型: 洪水
  目标区域: 四川某地
```

**Step 2：任务拆解（Task Plan）**

```
1. 调用 GraphRAG Tool → 获取洪水灾害背景知识
2. 调用 Browser Tool  → 获取该区域实时灾害信息
3. 调用 Remote Sensing Tool → 分析上传遥感影像
4. 调用 Risk Assessment Tool → 综合风险评估
5. 调用 Report Tool → 生成灾害评估报告
```

**Step 3：工具调用（Function Calling）**

Agent 按计划顺序调用工具，每步结果写入任务记忆。

**Step 4：结果融合**

```
遥感分析结果
    +
网络检索证据
    +
知识图谱推理
    +
用户上传文档
    ↓
综合风险评估结论
```

### 4.2 任务记忆结构

每个 Task 维护一份动态 Task Document，随 Agent 工作不断更新：

```json
{
  "task_id": "T202607081",
  "disaster_type": "洪水",
  "location": "四川 XX 县",
  "known_info": ["持续强降雨", "水位上涨预警"],
  "missing_info": ["实时遥感数据", "人员分布"],
  "evidence": [...],
  "analysis_result": {...},
  "conversation_summary": "..."
}
```

### 4.3 Agent 状态机

```
IDLE → PLANNING → EXECUTING → ANALYZING → REPORTING → DONE
                     ↑               |
                     └── 工具失败重试 ┘
```

---

## 5. 工具模块详细设计

### 5.1 Graph RAG 知识推理工具（GraphRAG Tool）

**功能：** 利用灾害知识图谱增强 Agent 推理，解答"为什么发生灾害？如何应对？"

**工作流程：**

```
灾害知识库 → GraphRAG Index → 实体关系抽取 → 知识图谱 → 图检索 → LLM 推理 → 输出结论
```

**知识图谱示例：**

```
暴雨 --[CAUSES]--> 河流水位上涨 --[TRIGGERS]--> 洪水 --[REQUIRES]--> 人员转移
                                                  |
                                              [AFFECTS]
                                                  ↓
                                              农田受损 / 道路中断
```

**输入：** 用户问题（如"该地区洪水风险较高的原因？"）

**输出示例：**

```
风险原因：
  1. 持续强降雨导致河流水位持续上涨
  2. 地形低洼，排水能力不足
  3. 历史记录显示该地区洪灾频发（近 10 年 5 次）

建议措施：
  提前转移低洼区域居民，加强 24 小时水位监测。

推理依据：
  知识图谱路径：暴雨 → 水位上涨 → 洪水 → 居民区受影响
```

**技术：** Microsoft GraphRAG · Neo4j · LLM（GLM/GPT）

---

### 5.2 文档理解工具（Document Tool）

**功能：** 解析用户上传的灾害相关资料，提取关键信息写入任务记忆。

**支持格式：** PDF · Word · TXT · Excel

**工作流程：**

```
文件上传 → 格式解析 → 文本切分 → Embedding → 向量存储 → 任务知识更新
```

**输出示例（Task Document 片段）：**

```
已提取信息：
  灾害类型: 洪水
  区域: 四川 XX 县
  已知条件: 强降雨持续 72 小时，水位超警戒线 0.8m
  缺失信息: 实时遥感影像，人员受灾统计
```

**技术：** PyMuPDF · LangChain Document Loader · Tesseract OCR

---

### 5.3 遥感分析工具（Remote Sensing Tool）

**功能：** 对用户上传的卫星影像进行灾害区域检测与面积计算。

**支持格式：** PNG · JPEG · GeoTIFF

**工作流程：**

```
遥感图片输入 → 图像预处理 → 视觉模型推理 → 灾害区域分割 → 面积计算 → 结果输出
```

**输出示例：**

```json
{
  "disaster_type": "洪水",
  "affected_area": "A 区域（东北部）",
  "area_km2": 3.2,
  "water_coverage_ratio": 0.42,
  "confidence": 0.91
}
```

**技术：** SegFormer · U-Net · YOLO（目标检测） · OpenCV

---

### 5.4 浏览器信息搜索工具（Browser Tool）

**功能：** 实时检索互联网信息，获取最新灾害动态与气象预警。

**数据来源：** 新闻网站 · 气象局官网 · 应急管理部平台 · 政府公告

**工作流程：**

```
构建搜索关键词 → 搜索 API 调用 → 网页内容抓取 → 文本清洗 → 证据入库
```

**输出示例：**

```json
{
  "source": "中国气象局",
  "url": "http://www.cma.gov.cn/...",
  "content": "未来 24 小时四川 XX 县存在暴雨红色预警，降水量预计超 150mm",
  "publish_time": "2026-07-08 08:00",
  "confidence": 0.95
}
```

**技术：** Search API（SerpAPI/Bing） · BeautifulSoup · Playwright

---

### 5.5 风险评估工具（Risk Assessment Tool）

**功能：** 融合多源分析结果，生成量化风险等级与应急建议。

**输入：**

```
遥感分析结果 + Graph RAG 推理结论 + 网络检索证据 + 用户文档摘要
```

**评分逻辑（加权融合）：**

| 来源 | 权重 |
|------|------|
| 遥感影像分析 | 35% |
| 实时网络信息 | 30% |
| 知识图谱推理 | 25% |
| 用户上传文档 | 10% |

**输出示例：**

```json
{
  "risk_score": 0.87,
  "risk_level": "高风险",
  "reason": ["持续暴雨（气象预警）", "水体面积扩大 42%（遥感）", "历史灾害频发（知识图谱）"],
  "suggestion": "立即启动二级应急响应，疏散低洼区域居民约 3200 人"
}
```

---

### 5.6 证据链工具（Evidence Tool）

**功能：** 汇总所有工具产出的依据，形成可追溯的分析证据链，提高结论可信度。

**输出示例：**

```
风险评估：高风险（评分 0.87）

佐证证据：
  ① [遥感] 检测到 A 区域水体面积扩张 3.2km²（置信度 0.91）
  ② [网络] 气象局发布暴雨红色预警，未来 24h 降水 >150mm
  ③ [知识图谱] 路径：暴雨 → 水位上涨 → 洪水，历史触发 5 次
  ④ [文档] 用户报告显示河堤警戒水位已超 0.8m
```

---

### 5.7 报告生成工具（Report Tool）

**功能：** 自动将分析结论整合为结构化灾害评估报告（PDF）。

**报告结构：**

```
灾害影响评估报告
├── 1. 摘要
├── 2. 灾害背景与区域概况
├── 3. 数据来源说明
├── 4. 遥感影像分析结果
├── 5. 综合风险评估
├── 6. 应急响应建议
├── 7. 证据链附录
└── 8. 参考资料
```

**技术：** ReportLab · WeasyPrint · Jinja2 模板

---

### 5.8 邮件通知工具（Email Tool）

**功能：** 报告生成后自动发送至指定邮箱。

**输入：**

```json
{
  "to": ["manager@example.com"],
  "subject": "【高风险预警】四川 XX 县洪水评估报告",
  "report_path": "reports/T202607081.pdf"
}
```

**技术：** SMTP · Python smtplib

---

## 6. 数据库设计

### 6.1 ER 图（概念模型）

```
User ──< Task >── Document
          |
          ├──< Conversation
          ├──< Tool_Call
          ├──< Evidence
          ├──< Analysis_Result
          └──< Report
```

### 6.2 MySQL 业务数据库

**用户表 `user`**

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | INT PK | 用户 ID |
| username | VARCHAR(50) | 用户名 |
| email | VARCHAR(100) | 邮箱 |
| password_hash | VARCHAR(255) | 密码哈希 |
| create_time | DATETIME | 注册时间 |

**任务表 `task`**

| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | INT PK | 任务 ID |
| user_id | INT FK | 所属用户 |
| task_name | VARCHAR(100) | 任务名称 |
| disaster_type | VARCHAR(50) | 灾害类型（洪水/地震等）|
| location | VARCHAR(100) | 目标区域 |
| status | ENUM | IDLE/RUNNING/DONE/ERROR |
| create_time | DATETIME | 创建时间 |

**对话表 `conversation`**

| 字段 | 类型 | 说明 |
|------|------|------|
| conv_id | INT PK | 对话 ID |
| task_id | INT FK | 关联任务 |
| role | ENUM | user / assistant / tool |
| content | TEXT | 消息内容 |
| created_at | DATETIME | 时间 |

**文件表 `document`**

| 字段 | 类型 | 说明 |
|------|------|------|
| doc_id | INT PK | 文件 ID |
| task_id | INT FK | 关联任务 |
| filename | VARCHAR(255) | 文件名 |
| file_type | VARCHAR(20) | PDF/DOCX/IMAGE |
| file_path | VARCHAR(500) | 存储路径 |
| upload_time | DATETIME | 上传时间 |

**任务知识表 `task_document`**（Agent 整理的结构化摘要）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | ID |
| task_id | INT FK | 关联任务 |
| content | JSON | 知识摘要（known/missing/summary）|
| version | INT | 版本号（每次更新递增）|
| updated_at | DATETIME | 更新时间 |

**工具调用表 `tool_call`**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | ID |
| task_id | INT FK | 关联任务 |
| tool_name | VARCHAR(50) | 工具名称 |
| input_params | JSON | 调用参数 |
| output | JSON | 返回结果 |
| status | ENUM | SUCCESS/FAILED |
| called_at | DATETIME | 调用时间 |

**证据表 `evidence`**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | ID |
| task_id | INT FK | 关联任务 |
| source | VARCHAR(100) | 来源（遥感/网络/知识图谱/文档）|
| content | TEXT | 证据内容 |
| confidence | FLOAT | 可信度（0-1）|
| created_at | DATETIME | 时间 |

**分析结果表 `analysis_result`**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | ID |
| task_id | INT FK | 关联任务 |
| risk_level | VARCHAR(20) | 低/中/高/极高 |
| risk_score | FLOAT | 风险评分（0-1）|
| reason | JSON | 风险原因列表 |
| suggestion | TEXT | 应急建议 |
| created_at | DATETIME | 时间 |

**报告表 `report`**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | ID |
| task_id | INT FK | 关联任务 |
| file_path | VARCHAR(500) | 报告 PDF 路径 |
| generated_at | DATETIME | 生成时间 |

---

### 6.3 Neo4j 知识图谱

**节点类型：**

| 节点标签 | 属性示例 |
|---------|---------|
| `Disaster` | name, type, severity |
| `Weather` | name, intensity |
| `Location` | name, province, lat, lon |
| `Impact` | name, category |
| `Action` | name, priority |

**关系类型：**

| 关系 | 含义 | 示例 |
|------|------|------|
| `CAUSES` | 导致 | 暴雨 → 洪水 |
| `TRIGGERS` | 触发 | 水位上涨 → 洪水 |
| `AFFECTS` | 影响 | 洪水 → 农田 |
| `LOCATED_IN` | 位于 | 洪水 → 四川 |
| `REQUIRES` | 需要 | 洪水 → 人员转移 |
| `MITIGATED_BY` | 缓解措施 | 洪水 → 堤坝加固 |

**Cypher 查询示例：**

```cypher
// 查询洪水的所有触发因素及应对措施
MATCH (cause)-[:CAUSES]->(d:Disaster {name: "洪水"})-[:REQUIRES]->(action)
RETURN cause.name, d.name, action.name
```

---

### 6.4 向量数据库（FAISS / Milvus）

**存储内容：** 文档切片向量 · 网络检索文本向量 · 历史对话摘要向量

**数据结构：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | STRING | 唯一 ID |
| vector | FLOAT[] | Embedding 向量（1536 维）|
| text | TEXT | 原始文本 |
| source | VARCHAR | 来源类型 |
| task_id | INT | 关联任务 |
| metadata | JSON | 附加元信息 |

---

### 6.5 本地文件系统

```
data/
├── uploads/          # 用户上传原始文件
│   ├── pdf/
│   ├── images/
│   └── docs/
├── remote_sensing/   # 遥感影像
│   ├── raw/
│   └── processed/
├── reports/          # 生成的评估报告
│   └── T202607081.pdf
└── knowledge/        # GraphRAG 索引缓存
```

---

## 7. 接口设计

### 7.1 RESTful API 总览

| 模块 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 用户 | POST | `/api/auth/register` | 用户注册 |
| 用户 | POST | `/api/auth/login` | 用户登录 |
| 任务 | POST | `/api/tasks` | 创建任务 |
| 任务 | GET | `/api/tasks` | 任务列表 |
| 任务 | GET | `/api/tasks/{id}` | 任务详情 |
| 任务 | DELETE | `/api/tasks/{id}` | 删除任务 |
| 对话 | POST | `/api/tasks/{id}/chat` | 发送消息 |
| 对话 | GET | `/api/tasks/{id}/chat` | 对话历史 |
| 文件 | POST | `/api/tasks/{id}/upload` | 上传文件 |
| 遥感 | POST | `/api/tasks/{id}/remote-sensing` | 提交遥感图片 |
| 分析 | GET | `/api/tasks/{id}/analysis` | 获取分析结果 |
| 报告 | GET | `/api/tasks/{id}/report` | 下载报告 |
| 报告 | POST | `/api/tasks/{id}/report/send` | 发送邮件 |

### 7.2 核心接口详细说明

**创建任务**

```http
POST /api/tasks
Authorization: Bearer <token>

{
  "task_name": "四川 XX 县洪水分析",
  "disaster_type": "洪水",
  "location": "四川省 XX 县"
}

Response 201:
{
  "task_id": 1001,
  "status": "IDLE",
  "created_at": "2026-07-08T10:00:00"
}
```

**发送消息（触发 Agent）**

```http
POST /api/tasks/{id}/chat
Authorization: Bearer <token>

{
  "message": "分析该区域洪水风险，生成评估报告"
}

Response 200（流式 SSE）:
data: {"type": "thinking", "content": "正在规划任务..."}
data: {"type": "tool_call", "tool": "GraphRAG", "status": "running"}
data: {"type": "tool_result", "tool": "GraphRAG", "content": "..."}
data: {"type": "answer", "content": "综合评估结果：高风险..."}
data: {"type": "done"}
```

**上传文件**

```http
POST /api/tasks/{id}/upload
Content-Type: multipart/form-data

file: <binary>

Response 200:
{
  "doc_id": 55,
  "filename": "灾害报告.pdf",
  "status": "processed"
}
```

---

## 8. 用例与流程图

### 8.1 系统用例图

```
用户
 ├── 注册 / 登录
 ├── 创建灾害任务
 ├── 上传灾害文档
 ├── 上传遥感影像
 ├── 与 Agent 对话
 │     ├── 触发知识推理
 │     ├── 触发实时检索
 │     ├── 触发遥感分析
 │     └── 触发报告生成
 ├── 查看分析结果
 ├── 下载评估报告
 └── 发送邮件通知
```

### 8.2 核心时序图（灾害分析全流程）

```
用户      前端       后端API     Agent     GraphRAG   Browser   Remote    DB
 |          |           |          |          |         |       Sensing   |
 |--发消息-->|           |          |          |         |          |      |
 |          |--POST chat->|          |          |         |          |      |
 |          |           |--dispatch->|          |         |          |      |
 |          |           |          |--意图识别--|          |         |      |
 |          |           |          |--规划Tasks-|          |         |      |
 |          |           |          |            |         |          |      |
 |          |           |          |--call------>|         |          |      |
 |          |           |          |<--知识结论--|          |         |      |
 |          |           |          |             |--search->|         |      |
 |          |           |          |<--证据------|-<result-|         |      |
 |          |           |          |             |         |--analyze->|    |
 |          |           |          |<--遥感结果--|         |<-result--|    |
 |          |           |          |--风险融合---|          |         |      |
 |          |           |          |--生成报告---|          |         |      |
 |          |           |          |--save result------------------------->|
 |          |<---SSE 流式返回-------|          |         |          |      |
 |<--结果显示|           |          |          |         |          |      |
```

### 8.3 文件上传处理时序

```
用户 → 上传 PDF → 后端保存文件 → Document Tool 解析
    → 文本切分 → Embedding → 写入 Vector DB
    → 更新 Task Document → 通知 Agent 任务知识已更新
```

---

## 9. 技术栈

| 层次 | 技术 | 说明 |
|------|------|------|
| 前端 | Vue3 + Element Plus | 交互界面 |
| 前端图表 | ECharts | 风险可视化 |
| 后端框架 | Python + FastAPI | RESTful API |
| Agent 框架 | LangChain Agent | Function Calling 调度 |
| LLM | GPT-4o / GLM-4 | 推理与生成 |
| 知识图谱 | Microsoft GraphRAG + Neo4j | 灾害知识推理 |
| 向量检索 | FAISS / Milvus | 语义相似检索 |
| Embedding | text-embedding-3-small | 文本向量化 |
| 遥感分析 | SegFormer / U-Net | 影像语义分割 |
| 文档解析 | PyMuPDF + Tesseract | PDF / 图片 OCR |
| 网络检索 | SerpAPI + Playwright | 实时信息获取 |
| 报告生成 | ReportLab + Jinja2 | PDF 报告 |
| 业务数据库 | MySQL 8.0 | 结构化业务数据 |
| 缓存 | Redis | 会话缓存 / 限流 |
| 对象存储 | MinIO / 本地 | 文件存储 |
| 容器化 | Docker + Docker Compose | 部署 |

---

## 10. 开发计划

### 第一阶段（基础系统，Week 1-2）

- [ ] 用户注册 / 登录（JWT 鉴权）
- [ ] 任务 CRUD 管理
- [ ] 文件上传与存储
- [ ] 基础对话界面

### 第二阶段（Agent 骨架，Week 3-4）

- [ ] LangChain Agent 集成
- [ ] 意图识别与任务规划
- [ ] Function Calling 框架搭建
- [ ] 任务记忆管理（Task Document）

### 第三阶段（AI 工具，Week 5-7）

- [ ] Graph RAG 知识图谱构建与接入
- [ ] 文档解析工具（PDF/OCR）
- [ ] 遥感影像分析（SegFormer 推理）
- [ ] 浏览器检索工具（SerpAPI）
- [ ] 向量数据库接入

### 第四阶段（闭环与优化，Week 8-9）

- [ ] 风险评估融合逻辑
- [ ] 证据链汇总工具
- [ ] PDF 报告自动生成
- [ ] 邮件通知
- [ ] Dashboard 可视化
- [ ] 系统联调测试

---

## 11. 部署架构

```
                    ┌──────────────────────────┐
                    │        Nginx             │
                    │  反向代理 + HTTPS + 限流   │
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
    ┌─────────▼─────────┐ ┌──────▼──────┐  ┌────────▼───────┐
    │  Frontend (Vue3)  │ │  FastAPI    │  │  LangChain     │
    │  静态资源服务       │ │  后端服务    │  │  Agent 服务     │
    └───────────────────┘ └──────┬──────┘  └────────┬───────┘
                                 │                  │
              ┌──────────────────┼──────────────────┤
              │                  │                  │
    ┌─────────▼────┐  ┌──────────▼──┐  ┌────────────▼──────┐
    │   MySQL 8.0  │  │   Neo4j     │  │  FAISS / Milvus   │
    │  业务数据      │  │  知识图谱    │  │  向量数据库         │
    └──────────────┘  └─────────────┘  └───────────────────┘
              │
    ┌─────────▼────┐  ┌─────────────┐
    │    Redis     │  │    MinIO    │
    │  缓存 / 队列  │  │  文件存储    │
    └──────────────┘  └─────────────┘
```

**Docker Compose 服务列表：**

| 服务 | 镜像 | 端口 |
|------|------|------|
| frontend | node:18-alpine | 3000 |
| backend | python:3.11-slim | 8000 |
| agent | python:3.11-slim | 8001 |
| mysql | mysql:8.0 | 3306 |
| neo4j | neo4j:5.x | 7474/7687 |
| redis | redis:7-alpine | 6379 |
| minio | minio/minio | 9000/9001 |

---

## 12. 项目创新点

### 1. 任务记忆增强 Agent

与普通问答机器人不同，本系统以"灾害任务"为工作单元，Agent 持续维护任务上下文（历史对话、已知信息、分析结果），实现跨对话的持续智能分析。

### 2. Graph RAG 灾害推理

将灾害知识体系构建为知识图谱（灾害—原因—影响—应对措施），通过 GraphRAG 增强 LLM 对灾害因果逻辑的推理能力，提升结论的专业性与可解释性。

### 3. 多模态灾害感知

融合文本（报告/新闻）、图像（遥感影像）、结构化知识（图谱）三类模态，形成比单一文本 RAG 更全面的灾害感知能力。

### 4. 自主工具调度

Agent 基于用户意图自动规划工具调用顺序，无需手动指定分析步骤，降低使用门槛。

### 5. 证据链驱动分析

每条结论均附有可追溯的多源证据（来源、置信度、原始内容），增强决策透明度与可信度。

---

*文档版本：v1.0 | 日期：2026-07-08*



