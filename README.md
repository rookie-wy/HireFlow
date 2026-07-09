# AI招聘Agent系统

基于可编排的多Agent协作架构，实现从简历解析、多维匹配、多专家评估、面试调度到人才池沉淀的全链路智能化招聘助手。支持云端/本地混合部署，提供可解释的决策过程与透明的成本模型。

## 功能特性

- **简历智能解析**：支持 PDF/Word/图片格式，利用 MinerU + pdfplumber 双链路提取文本，通过 LLM 结构化输出候选人档案
- **JD解析**：自动提取硬性条件、软性要求、技能图谱，生成标准化岗位画像
- **混合粗筛**：HyDE 查询改写 + 稠密/稀疏双路召回 + RRF 融合 + Cross-Encoder 重排序 + Self-RAG 反思
- **多Agent精筛**：根据岗位类别动态激活面试官、技能评估、文化契合等 Agent，支持辩论-仲裁机制
- **可解释报告**：综合得分、维度小分、推荐理由及原文证据高亮
- **记忆与反馈**：短期记忆支持断点恢复，长期记忆跨岗位复用候选人，HR反馈实时调整个人排序权重
- **面试调度**：生成面试邀请草稿，确认后发送邮件并同步日历（MCP工具）
- **多租户隔离**：基于租户ID的数据隔离，RBAC权限控制
- **前端交互**：Streamlit 纯Python界面，支持简历上传、职位管理、智能筛选、面试调度，数据持久化

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| Agent编排 | LangGraph |
| LLM网关 | LiteLLM (DeepSeek) |
| 嵌入模型 | BGE-M3 (备选 MiniLM) |
| 重排序 | BGE-Reranker-v2-m3 |
| 向量数据库 | ChromaDB |
| 关系数据库 | MySQL |
| 缓存/锁 | Redis |
| 消息队列 | Celery |
| 文档解析 | MinerU / pdfplumber / PaddleOCR |
| 前端 | Streamlit |
| 监控 | LangFuse + OpenTelemetry (预留) |
| 部署 | Docker Compose |

## 快速开始

### 环境要求
- Python 3.11+
- Docker 20.10+ (用于 MySQL、Redis、ChromaDB)
- DeepSeek API Key

### 1. 克隆项目并进入目录
```bash
git clone <your-repo-url>
cd ai-recruitment-agent
```

### 2. 安装依赖
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env，填入你的 DEEPSEEK_API_KEY 和 OPENAI_API_KEY (同为DeepSeek Key)
# 可修改数据库连接、Redis地址等
```

### 4. 启动依赖服务
```bash
docker-compose up -d db redis chroma
```

### 5. 初始化数据库
```bash
# 连接 MySQL 执行 init_db.sql
mysql -u root -p recruitment < src/app/db/init_db.sql
```

### 6. 启动后端
```bash
export PYTHONPATH=src   # Windows: $env:PYTHONPATH="src"
python -m app.main
```
后端运行在 `http://localhost:8000`，API文档 `http://localhost:8000/docs`

### 7. 启动前端 (新终端)
```bash
streamlit run frontend_app.py
```
前端运行在 `http://localhost:8501`

### 8. (可选) 启动 Celery Worker
```bash
celery -A app.infrastructure.celery_app worker -l info -Q parse_resume,send_email,generate_summary
```

## 项目结构

```
├── src/
│   ├── app/
│   │   ├── main.py                 # FastAPI入口
│   │   ├── core/                   # 配置、异常、安全、日志
│   │   ├── api/v1/                 # 路由 (jobs, candidates, screen, interview, feedback)
│   │   ├── db/                     # MySQL 连接池、Repository、DDL
│   │   ├── models/                 # 领域实体、Pydantic模型、枚举
│   │   ├── services/               # 业务逻辑
│   │   │   ├── parsing/            # JD/简历解析、技能图谱、向量化
│   │   │   ├── screening/          # 粗筛、精筛、Agent、仲裁
│   │   │   ├── memory/             # 短期记忆、交互日志、岗位摘要
│   │   │   ├── feedback/           # 反馈权重调整
│   │   │   └── scheduling/         # 面试调度
│   │   ├── agents/                 # LangGraph 状态图与节点
│   │   └── infrastructure/         # LLM、Redis、Chroma、Celery、MCP等中间件
│   ├── frontend_app.py             # Streamlit 前端
│   └── requirements.txt
├── docker-compose.yml
├── .env.example
└── README.md
```

## 接口示例

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/jobs` | 上传JD解析 |
| POST | `/api/v1/candidates/upload` | 上传简历解析 |
| GET | `/api/v1/candidates` | 获取候选人列表 |
| POST | `/api/v1/screen` | 执行智能筛选 |
| GET | `/api/v1/match_results?job_id=xxx` | 获取筛选结果 |
| POST | `/api/v1/interview/send` | 发送面试邀请 |
| POST | `/api/v1/feedback` | 提交候选人反馈 |
| DELETE| `/api/v1/candidates/{id}` | 删除候选人 |

## 使用流程

1. **上传简历**：在左侧导航「简历上传」页面上传候选人简历，系统自动解析并存储。
2. **解析岗位**：切换到「职位管理」，粘贴或输入JD文本，AI提取硬性/软性要求。
3. **智能筛选**：进入「智能筛选」，选择岗位，可选输入额外查询，点击“开始筛选”。系统会依次执行硬性过滤、粗筛、精筛，最终展示候选人卡片（含总分、维度分、证据）。
4. **反馈与优化**：对每个候选人标记“合适/不合适/待定”，系统会记住你的偏好，后续筛选结果将个性化调整。
5. **面试调度**：在筛选结果中选择候选人，设定时间，发送面试邀请（需配置邮件服务）。

## 后续计划

- [ ] 启用 Celery 异步任务，提升响应速度
- [ ] 记忆系统全链路集成，实现历史候选人重用
- [ ] 对接真实邮件与日历服务
- [ ] 部署监控告警 (Prometheus + Grafana)
- [ ] 纯本地版模型打包 (vLLM + 量化模型)
- [ ] 增加用户登录与权限管理界面

## 贡献指南

欢迎提交 Issue 或 Pull Request。本项目遵循 [MIT License](LICENSE)。

## 联系

如有问题或建议，请联系项目维护者。