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

本项目设计一个**灾害智能 Agent 系统**，以自然对话为入口，以工具能力池为执行基础。Agent 首先识别用户意图，再按需调用 Graph RAG、浏览器检索与截图理解、文档理解、遥感分析、任务草稿、风险评估、报告生成等工具。用户既可以进行普通问答、实时检索、图像识别，也可以在需要时触发完整灾害分析。

**核心交互模式：**

```
用户输入 → 意图识别 → 按需调用工具 → LLM 整合回答
                     ↓
          若识别为灾害分析需求
                     ↓
      生成临时任务文档 → 用户确认保留信息 → 正式风险分析 / 报告生成 / 通知
```

### 1.3 面向用户

- 应急管理人员
- 灾害分析研究人员
- 科研机构人员

---

## 2. 系统目标

### 2.1 对话优先的智能交互

用户不一定先创建完整灾害任务，也不一定按固定流程操作。系统支持以下交互模式：

- 普通灾害知识问答
- 基于 Graph RAG 的专业知识推理
- 实时新闻、气象预警、政府公告检索
- 浏览器网页截图与视觉理解
- 用户上传文档解析
- 用户上传遥感影像识别
- 用户确认后的灾害风险分析与报告生成

### 2.2 自主工具调用

Agent 根据用户意图自动规划并调用工具。工具不是固定流水线，而是可复用能力池：

- Intent Router 意图识别
- Graph RAG 知识推理
- 浏览器检索、网页读取、网页截图与截图理解
- 文档解析与理解
- 遥感影像分析
- 临时任务文档与任务记忆管理
- 风险评估与报告生成
- 邮件通知

### 2.3 临时任务文档与用户确认

当 Agent 判断用户正在进入灾害分析场景时，系统不会立即把所有对话内容写入正式任务记忆，而是先生成一份临时任务文档：

- 已知灾害类型、地点、时间与背景
- 用户上传资料中的候选关键信息
- 浏览器检索与截图理解得到的候选证据
- 遥感或图片识别结果
- 缺失信息与待核验假设

用户确认哪些信息有必要留下后，系统才将其写入正式任务记忆，并基于确认后的信息执行风险评估、报告生成或邮件通知。

### 2.4 多模态灾害感知

| 模态 | 数据类型 |
|------|---------|
| 文本 | 灾害报告、新闻公告、气象预警 |
| 图像 | 卫星遥感影像、网页截图、地图截图、气象图 |
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
│        对话界面 · 文件上传 · 临时任务文档确认 · 结果展示        │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                   Disaster Agent Core                        │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│ │ IntentRouter │ │ Tool Planner │ │ Draft / Memory Guard │ │
│ └──────────────┘ └──────────────┘ └──────────────────────┘ │
│                  Function Calling Dispatcher                  │
└────┬────────┬────────┬────────┬────────┬────────┬────────────┘
     │        │        │        │        │        │
 GraphRAG  Browser  Document  Remote  TaskDraft  Risk/Report/Email
            │                  Sensing      │
        Search · Page Read · Screenshot · Vision Understanding
┌────▼────────▼────────▼────────▼────────▼────────▼────────────┐
│                         数据存储层                            │
│        MySQL · Neo4j · Vector DB · 本地文件系统               │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Agent 核心设计

### 4.1 弹性控制流程

Agent 每轮对话都先进行意图识别，再决定是否进入灾害分析。用户可以只问一个知识问题，也可以只要求检索实时信息或识别图片。

**普通问答示例：**

```
输入: "洪水为什么常由持续强降雨触发？"
输出:
  意图: knowledge_or_general_qa
  工具: GraphRAG Tool
  动作: 检索灾害知识图谱并由 LLM 整合回答
```

**实时检索与截图理解示例：**

```
输入: "帮我看一下四川今天有没有暴雨预警，必要时看官网截图"
输出:
  意图: realtime_search
  工具: Browser Tool
  动作: 搜索官网公告，打开网页，必要时截图并理解页面地图/图表/预警颜色
```

**灾害分析示例：**

```
输入: "结合刚才的资料，分析这个县的洪水风险"
输出:
  意图: disaster_analysis
  工具: TaskDraft Tool → 用户确认 → RiskAssessment Tool
  动作: 先生成临时任务文档，用户确认保留信息后再进行风险评估
```

### 4.2 工具调度原则

- 工具按意图动态组合，不按固定流水线强制执行。
- GraphRAG、Browser、Document、Remote Sensing 等工具可以被多个场景复用。
- Browser Tool 不只负责文本搜索，也负责网页打开、截图和截图理解。
- Remote Sensing Tool 只处理用户上传的遥感/卫星影像，不负责网页截图。
- 灾害分析前必须经过临时任务文档整理与用户确认。
- 每个工具返回结构化结果，包括摘要、证据、置信度、产物路径和是否需要用户确认。

### 4.3 临时任务文档结构

当进入灾害分析意图时，系统先维护一份临时 Task Draft：

```
{
  "task_id": "T202607081",
  "status": "draft",
  "candidate_disaster_type": "洪水",
  "candidate_location": "四川 XX 县",
  "known_info": ["持续强降雨", "水位上涨预警"],
  "missing_info": ["实时遥感数据", "人员分布"],
  "candidate_evidence": [
    {
      "source": "browser",
      "content": "气象部门发布暴雨预警",
      "confidence": 0.95,
      "confirmed": false
    }
  ],
  "conversation_summary": "..."
}
```

用户确认后，才将 `confirmed=true` 的信息写入正式任务记忆。

### 4.4 正式任务记忆结构

每个 Task 维护一份动态 Task Document，随用户确认与 Agent 工作不断更新：

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

### 4.5 Agent 状态机

```
CHAT → INTENT_ROUTING → TOOL_USE → LLM_SYNTHESIS → CHAT
              │
              └── DISASTER_ANALYSIS_DETECTED
                         ↓
                  TEMP_TASK_DRAFT
                         ↓
                  USER_CONFIRM_MEMORY
                         ↓
                  RISK_ASSESSMENT
                         ↓
                  REPORT / NOTIFY / CHAT
```

---

## 5. 工具模块详细设计

第一版工具池包含 **10 个业务工具 + 1 个基类**。工具不是固定流水线步骤，而是 Agent 根据意图动态组合的能力单元。

### 5.1 统一工具返回结构

每个工具返回结构化 `ToolResult`，便于 LLM 整合、证据链追踪和用户确认：

```json
{
  "summary": "工具结果摘要",
  "evidence": [
    {
      "source": "browser / graphrag / document / remote_sensing",
      "type": "web / graph_path / document / image_analysis",
      "content": "可追溯证据内容",
      "confidence": 0.95
    }
  ],
  "artifacts": [
    {
      "type": "screenshot / report / processed_image",
      "path": "data/..."
    }
  ],
  "confidence": 0.9,
  "need_user_confirm": true,
  "data": {}
}
```

### 5.2 Intent Router Tool

**功能：** 识别用户意图，并规划本轮需要调用的工具。

**可识别意图：**

- 普通知识问答
- Graph RAG 专业推理
- 浏览器实时搜索
- 网页截图理解
- 文档理解
- 遥感影像识别
- 灾害风险分析
- 报告生成
- 邮件通知

**输出示例：**

```json
{
  "intent": "disaster_analysis",
  "tools": ["task_draft", "browser", "graphrag", "risk_assessment"],
  "need_user_confirm": true
}
```

### 5.3 GraphRAG Tool

**功能：** 利用灾害知识图谱增强 Agent 推理，回答灾害原因、影响路径、应急措施等问题。

**典型用途：**

- 普通知识问答
- 灾害因果链推理
- 风险评估中的历史规律与专业依据补充

**技术：** Microsoft GraphRAG · Neo4j · LLM（GLM/GPT）

### 5.4 Browser Tool

**功能：** 联网搜索、打开网页、抽取正文、网页截图、截图理解。

**注意：** 截图理解属于 Browser Tool 的增强能力。Agent 可以主动打开网页并截图，用户不需要手动截图。

**适用场景：**

- 新闻、气象预警、政府公告搜索
- 官方网页正文抽取
- 地图、雷达图、预警色块、网页图表截图理解
- 将 URL、页面文本、截图路径作为证据返回

**技术：** Search API（SerpAPI/Bing） · Playwright · BeautifulSoup · VLM

### 5.5 Document Tool

**功能：** 解析用户上传的 PDF、Word、TXT、Excel，提取候选关键信息。

**重要约束：** 文档解析结果默认进入临时任务文档，不直接写入正式任务记忆。

**技术：** PyMuPDF · LangChain Document Loader · Tesseract OCR · Embedding

### 5.6 Remote Sensing Tool

**功能：** 分析用户上传的遥感/卫星影像，识别灾害区域并估算受影响面积。

**边界：** 只处理用户上传的遥感影像；网页地图截图、气象图截图由 Browser Tool 负责。

**技术：** SegFormer · U-Net · YOLO · OpenCV

### 5.7 Task Draft Tool

**功能：** 当 Agent 判断用户正在进入灾害分析场景时，生成本次对话的临时任务文档。

**内容：**

- 候选灾害类型与地点
- 已知信息
- 缺失信息
- 候选证据
- 待用户确认的问题

**输出：** 临时 Word/结构化草稿，供用户选择哪些信息需要保留。

### 5.8 Memory Tool

**功能：** 在用户确认后，将临时任务文档中的必要信息写入正式任务记忆。

**写入内容：**

- 用户确认的事实
- 用户确认的证据
- 对话摘要
- 工具调用结果摘要
- 任务记忆版本号

### 5.9 Risk Assessment Tool

**功能：** 仅在灾害分析意图被确认后调用，融合多源证据生成风险评分、风险等级、原因和建议。

**输入：**

```
已确认任务记忆 + GraphRAG 证据 + Browser 证据 + Document 证据 + Remote Sensing 证据
```

**输出示例：**

```json
{
  "risk_score": 0.87,
  "risk_level": "高风险",
  "reason": ["持续暴雨（气象预警）", "水体面积扩大（遥感）", "历史洪灾频发（知识图谱）"],
  "suggestion": "启动应急响应，优先核验低洼区域人员与道路通行情况",
  "evidence": []
}
```

### 5.10 Report Tool

**功能：** 根据用户确认后的任务记忆、风险评估结果和证据链生成 PDF/Word 报告。

**报告结构：**

```
灾害影响评估报告
├── 1. 摘要
├── 2. 灾害背景与区域概况
├── 3. 数据来源说明
├── 4. 多源证据摘要
├── 5. 综合风险评估
├── 6. 应急响应建议
├── 7. 证据链附录
└── 8. 参考资料
```

**技术：** ReportLab · WeasyPrint · Jinja2 模板

### 5.11 Email Tool

**功能：** 将报告或预警结论发送至指定邮箱。

**技术：** SMTP · Python smtplib

### 5.12 暂不独立拆分的能力

- Evidence：第一版作为每个工具返回结构里的 `evidence` 字段，不单独做工具。
- Vision：网页截图理解归 Browser Tool，遥感影像理解归 Remote Sensing Tool。
- File Manager：第一版由上传接口、Document Tool、Browser Tool、Report Tool 分别管理产物路径，后续文件规模扩大后再独立拆分。

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
 ├── 与 Agent 普通问答
 ├── 发起实时检索 / 网页截图理解
 ├── 上传灾害文档
 ├── 上传遥感影像并请求识别
 ├── 创建或进入灾害任务
 ├── 与 Agent 对话
 │     ├── 触发知识推理
 │     ├── 触发实时检索与截图理解
 │     ├── 触发文档理解
 │     ├── 触发遥感分析
 │     ├── 生成临时任务文档
 │     ├── 用户确认保留信息
 │     └── 触发风险评估 / 报告生成 / 邮件通知
 ├── 查看分析结果
 ├── 下载评估报告
 └── 发送邮件通知
```

### 8.2 核心时序图（弹性对话与灾害分析）

```
用户      前端       后端API      Agent        Tool Pool        DB
 |          |           |           |              |             |
 |--发消息-->|           |           |              |             |
 |          |--POST chat->|         |              |             |
 |          |           |--dispatch->|             |             |
 |          |           |           |--IntentRouter|             |
 |          |           |           |--按需调用---->|             |
 |          |           |           |<--工具结果----|             |
 |          |           |           |--LLM整合回答--|             |
 |          |<---SSE 流式返回--------|              |             |
 |<--结果显示|           |           |              |             |
 |          |           |           |              |             |
 |--要求分析灾害-------->|           |              |             |
 |          |           |           |--生成临时任务文档-------->|
 |<--确认哪些信息保留----|           |              |             |
 |--确认保留------------>|           |              |             |
 |          |           |           |--写入正式任务记忆----------------->|
 |          |           |           |--风险评估 / 报告 / 通知----------->|
 |          |<---分析结果 / 报告链接---|              |             |
```

### 8.3 文件上传处理时序

```
用户 → 上传 PDF → 后端保存文件 → Document Tool 解析
    → 文本切分 → Embedding → 写入 Vector DB
    → 生成候选摘要 → 写入临时任务文档
    → 用户确认 → 更新正式 Task Document
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
| 网络检索 | SerpAPI + Playwright + VLM | 实时信息获取、网页截图与截图理解 |
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
- [ ] Intent Router 意图识别与工具规划
- [ ] 10 个工具的统一 ToolResult 返回结构
- [ ] Function Calling Dispatcher 框架搭建
- [ ] 临时任务文档（Task Draft）与用户确认机制
- [ ] 正式任务记忆管理（Task Document）

### 第三阶段（AI 工具，Week 5-7）

- [ ] Graph RAG 知识图谱构建与接入
- [ ] 文档解析工具（PDF/OCR）
- [ ] 遥感影像分析（SegFormer 推理）
- [ ] 浏览器检索、网页打开、截图与截图理解工具
- [ ] 向量数据库接入

### 第四阶段（闭环与优化，Week 8-9）

- [ ] 风险评估融合逻辑
- [ ] 工具级 evidence 证据结构与追溯展示
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
