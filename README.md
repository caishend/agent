# SkyGuard 灾害智能分析 Agent

基于 Graph RAG 与任务记忆增强的多模态遥感灾害智能分析系统。

## 快速启动

### 后端

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env   # 填写 .env 配置
uvicorn app.main:app --reload --port 8000
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
