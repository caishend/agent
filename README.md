# SkyGuard 灾害智能分析 Agent

基于 Graph RAG 与任务记忆增强的多模态遥感灾害智能分析系统。

## 快速启动

> 如果只是跑基础对话/文档问答，配置 MySQL + LLM + 搜索即可；如果要和当前开发机一样“满血运行”，还需要 Playwright、Neo4j、SMTP、GeoJSON 与人口密度预处理数据。

### 后端

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env   # 填写 .env 配置
uvicorn app.main:app --reload --reload-dir app --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

### Docker 一键启动

```bash
cp .env.example .env   # 填写配置
docker-compose up -d
```

## 组员满血运行指南

### 1. 环境准备

推荐统一使用 Conda 环境，例如：

```bash
conda create -n ml python=3.10 -y
conda activate ml
```

后端依赖：

```bash
cd backend
pip install -r requirements.txt
```

前端依赖：

```bash
cd frontend
npm install
```

浏览器截图依赖 Playwright Chromium：

```bash
conda activate ml
python -m playwright install chromium
```

如果 `playwright install chromium` 提示命令不存在，使用上面的 `python -m playwright install chromium`。

### 2. `.env` 配置

从模板复制：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

至少需要配置：

```env
# MySQL
MYSQL_URL=mysql+pymysql://root:你的密码@localhost:3306/skyguard

# JWT
SECRET_KEY=skyguard-local-dev-secret-please-change
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# 文件目录
UPLOAD_DIR=data/uploads
REPORT_DIR=data/reports

# 搜索：推荐博查 Bocha
BOCHA_API_KEY=你的博查APIKEY
BOCHA_API_URL=https://api.bocha.cn/v1/web-search
SERP_API_KEY=

# LLM：当前项目按 OpenAI-compatible 接口调用
OPENAI_API_KEY=你的APIKEY
OPENAI_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro

# Neo4j：用于知识图谱，可先不填；要看图谱就配置
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=你的Neo4j密码

# 邮件：要测试发送报告才需要
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_FROM_NAME=SkyGuard
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_TIMEOUT_SECONDS=10
```

注意：`.env` 不要提交到 Git。

### 3. 数据库启动

MySQL 需要先创建库：

```sql
CREATE DATABASE skyguard DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

后端启动时会自动创建/补齐表结构，包括：任务、会话、文档、态势总览、知识图谱、人口缓存等表。

Neo4j Community 可选，用于 GraphRAG 图谱写入与展示：

```text
地址：bolt://localhost:7687
账号：neo4j
密码：填入 .env 的 NEO4J_PASSWORD
```

如果只是演示普通对话、文档问答、报告生成，可以先不启动 Neo4j；如果要展示态势总览里的任务图谱，需要启动。

### 4. 本地地理数据与人口密度数据

态势总览地图与人口影响评估依赖本地数据。不要把大型原始数据 push 到 Git。

推荐目录：

```text
backend/data/
├── 中国国界和省界的GeoJson格式数据/   # 中国国界/省界 GeoJSON，可按实际文件名放置
├── cn.tif                              # 人口密度 GeoTIFF，可选
└── chn_pop_2025_CN_100m_R2025A_v1.tif  # WorldPop 100m 人口栅格，可选
```

说明：

- GeoJSON 边界文件用于 `/api/overview/china-geojson`。
- GeoTIFF 很大，不建议运行时直接渲染；项目支持预处理成 MySQL 缓存。
- 如果没有本地人口数据，系统会退回内置城市级演示人口数据，但影响人数估算不会完整。

人口密度预处理命令：

```bash
cd backend
python scripts/preprocess_population_cache.py --reset --stride 420 --max-samples 3500
```

参数说明：

- `--reset`：清空旧的人口缓存后重建。
- `--stride 420`：按间隔采样 GeoTIFF，数值越小越精细但越慢。
- `--max-samples 3500`：限制热力点数量，避免前端地图过重。

预处理后数据会写入 MySQL：

- `population_raster_sample`：人口热力点/估算采样点。
- `admin_population_stat`：行政区人口统计缓存。

### 5. 启动顺序

后端：

```bash
conda activate ml
cd backend
uvicorn app.main:app --reload --reload-dir app --port 8000
```

前端：

```bash
cd frontend
npm run dev
```

访问：

```text
前端：http://localhost:3000
后端：http://127.0.0.1:8000
接口文档：http://127.0.0.1:8000/docs
```

### 6. 满血功能检查清单

- 登录/注册：MySQL 正常，JWT 正常。
- 普通对话：LLM Key 正常。
- 网页搜索：`BOCHA_API_KEY` 正常。
- 浏览器截图：`python -m playwright install chromium` 已执行。
- 文档问答：上传 PDF/DOCX/TXT/MD 后能解析。
- GraphRAG：Neo4j 启动且 `.env` 密码正确。
- 灾害分析报告：LLM + 搜索 + 文档 + 报告目录可写。
- 报告预览/下载：`backend/data/reports` 会通过 `/artifacts/reports` 暴露。
- 态势总览地图：GeoJSON 文件存在。
- 人口热力/影响人数：已运行人口密度预处理脚本。
- 邮件发送：SMTP 配置完整。

### 7. 不要提交的数据与密钥

以下内容不要 push：

```text
.env
backend/.env
frontend/.env
backend/data/uploads/
backend/data/reports/
backend/data/screenshots/
backend/data/*.tif
backend/data/**/*.tif
backend/data/*.tiff
backend/data/**/*.tiff
backend/data/*.zip
backend/data/**/*.zip
```

提交前建议检查：

```bash
git status
git diff --stat
git ls-files backend/data
```

如果不小心把大数据或运行产物加入了 Git，使用 `--cached` 移除追踪，不删除本地文件：

```bash
git rm --cached -r backend/data/uploads backend/data/reports backend/data/screenshots
git rm --cached backend/data/你的大文件.tif
```

然后重新提交 `.gitignore` 与代码即可。

### 8. 常见问题

**Playwright 命令不存在**

```bash
python -m playwright install chromium
```

**截图是 404 或反爬页**

搜索结果可能来自坏站点。当前 BrowserTool 会过滤论坛/归档/404 链接，并优先尝试气象、政府、新闻类权威页面；如果仍失败，看执行轨迹里的 URL 与失败原因。

**报告不在右侧相关文档里**

重启后端和前端，重新生成报告。新报告会登记进 `document` 表，并显示在右侧“相关文档”。

**删除文档后还被 RAG 用到**

当前删除接口会清理文件、`document` 表、当前 Agent session 文档缓存和知识图谱引用。若后续接入持久化向量库，需要在删除接口里额外调用向量库 delete。

**态势总览没有人口热力图**

确认已放置本地人口 GeoTIFF，并运行：

```bash
cd backend
python scripts/preprocess_population_cache.py --reset --stride 420 --max-samples 3500
```

## 目录说明

```
├── frontend/     Vue3 前端
├── backend/      FastAPI + LangChain Agent
│   └── app/
│       ├── api/        路由层
│       ├── models/     ORM 数据模型
│       ├── agent/      Agent 核心 + 工具集
│       ├── db.py       数据库连接
│       ├── config.py   配置
│       └── utils.py    JWT / 文件 / 邮件工具
├── knowledge/    GraphRAG 知识库
├── data/         运行时数据（上传文件、报告）
└── deploy/       Nginx 配置 + MySQL 建表脚本
```
