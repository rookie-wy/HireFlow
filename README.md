# AI 招聘 Agent 系统

面向企业招聘场景的 AI 中台：**JD 解析 → 简历解析 → 向量检索 + 混合粗筛 → 多 Agent 圆桌讨论精筛 → 面试邮件调度**。
三服务架构，职责边界清晰：Golang 负责业务与状态，Python 负责 AI 能力，React 负责交互。

---

## 一、架构总览

```
                          ┌───────────────────────────────┐
                          │  浏览器 / HR 用户              │
                          └───────────────┬───────────────┘
                                          │ HTTP / SSE
                       ┌──────────────────▼──────────────────┐
                       │ frontend  React18 + Vite5 + AntD5    │
                       │ 生产：nginx 托管 dist                │
                       │       /api/ → backend:8080           │
                       │       （SSE 关闭缓冲，600s 读超时）  │
                       └──────────────────┬──────────────────┘
                                          │ /api/v1/**
                    ┌─────────────────────▼─────────────────────┐
                    │ backend  Golang + Gin （业务中台，8080）   │
                    │  · JWT 鉴权 / 角色（hr·manager·admin）     │
                    │  · MySQL 7 表（启动时内嵌迁移）            │
                    │  · Redis 滑动窗口限流 / 事件通道 / 幂等锁  │
                    │  · 筛选任务队列（4 worker，队列 64）       │
                    │  · SSE 推送筛选进度                        │
                    └───┬───────────────┬───────────────┬───────┘
                        │               │               │
              MySQL DSN │      Redis    │   HTTP + X-Internal-Key
                        │               │               │
        ┌───────────────▼──┐  ┌─────────▼──────┐  ┌─────▼──────────────────────┐
        │  MySQL 8.0       │  │  Redis 7       │  │ agent  Python3.13+FastAPI  │
        │  users/jobs/...  │  │  限流·事件·锁   │  │ （AI 能力服务，8001）       │
        └──────────────────┘  └────────────────┘  │  · LLM 调用（DeepSeek）     │
                                                   │  · 文档解析（PyMuPDF）      │
                                                   │  · 嵌入/重排（BGE-M3）      │
                                                   │  · 混合粗筛（向量+BM25+RRF）│
                                                   │  · 多 Agent 圆桌讨论        │
                                                   └───┬─────────────┬──────────┘
                                                       │             │
                                            ┌──────────▼───┐  ┌──────▼─────────┐
                                            │ ChromaDB     │  │ DeepSeek API   │
                                            │ 向量库        │  │ (外网 HTTPS)   │
                                            └──────────────┘  └────────────────┘
                                                       │
                                            ┌──────────▼────────────────────┐
                                            │ mock MCP 工具（外部，可选）     │
                                            │ 9000 邮件 / 9001 日历          │
                                            └───────────────────────────────┘
```

**边界约定（改动前先看）**

- agent **不直连 MySQL**：业务数据由 backend 随请求传入，agent 只写 ChromaDB。
- backend 与 agent 之间用 `X-Internal-Key` 请求头鉴权（两端 `AGENT_INTERNAL_KEY` 必须一致），`/healthz` 豁免。
- 前端流式读 SSE 用的是 `fetch`（`EventSource` 无法携带 `Authorization` 头），因此 nginx 必须关闭 `proxy_buffering`。

---

## 二、技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 · Vite 5 · TypeScript 5 · Ant Design 5 · Zustand · Axios |
| 业务后端 | Golang（go.mod 声明 go 1.24）· Gin 1.10 · GORM · MySQL 8.0 · Redis 7 · JWT v5 · zerolog · 自研轻量指标注册表（零依赖） |
| AI 服务 | Python 3.13 · FastAPI · uvicorn · pydantic-settings · openai SDK（DeepSeek 兼容）· chromadb · sentence-transformers / FlagEmbedding（BGE-M3 + Reranker）· rank-bm25 · PyMuPDF · 自研轻量指标注册表（零依赖） |
| 向量库 | ChromaDB（**镜像必须 1.0.15**） |
| 部署 | Docker Compose（六容器）· nginx 1.27 · 多阶段构建 |
| 可观测性 | 双端 `/metrics`（Prometheus 文本格式，无需额外 exporter）；成本/token/缓存命中/任务耗时/连接池/业务存量 |

---

## 三、目录结构

```
PythonProject2/
├── backend/                     # Go 业务中台
│   ├── cmd/server/              #   入口（main.go：迁移 → HTTP → 优雅停机）
│   ├── internal/
│   │   ├── config/              #   环境变量配置（全默认值，production 密钥 fail-fast）
│   │   ├── database/            #   连接 + 内嵌迁移（0001 建表 / 0002 幂等缓存 / 0003 岗位配置 / 0004 配置指纹）
│   │   │                        #   7 张业务表：users/jobs/candidates/match_results/
│   │   │                        #   interaction_log/cost_records/screening_tasks
│   │   ├── handler/             #   HTTP 处理器（auth/business/screen/feedback/interview/health/metrics）
│   │   ├── middleware/          #   JWT 鉴权、角色、限流、CORS、Recovery、Trace、日志+HTTP 指标
│   │   ├── model/               #   GORM 模型
│   │   ├── repository/          #   数据访问（含候选人分页加载）
│   │   ├── service/             #   业务逻辑（筛选 worker 池、断点续跑、幂等缓存编排）
│   │   ├── pkg/                 #   jwtutil / agentclient / redisclient / apperror / logger /
│   │   │                        #   metrics（指标注册表）/ fingerprint（简历+岗位配置指纹）
│   │   └── router/              #   路由装配
│   ├── Dockerfile               #   多阶段：golang:1.24-alpine → alpine:3.20（非 root）
│   └── go.mod / go.sum
├── agent/                       # Python AI 能力服务
│   ├── app/
│   │   ├── main.py              #   FastAPI 入口（uvicorn app.main:app，启动后台预热模型）
│   │   ├── api/                 #   health（含 /healthz/metrics） / parsing / screening / interview 路由
│   │   ├── agents/              #   多 Agent 圆桌：registry（含岗位级权重解析）/ experts / moderator / engine
│   │   ├── core/                #   config / security / errors / metrics（指标注册表）
│   │   ├── infra/               #   llm_client（含成本埋点）/ chroma_client / embedding_client（并发推理锁）/ mcp_client / pii
│   │   └── services/            #   parsing / screening（hybrid_screener + reranker 策略 + orchestrator）/ interview
│   ├── tests/                   #   pytest（34 项：流程/并发/词边界/指标不变量/岗位配置）
│   ├── models/                  #   本地权重（bge-m3 / bge-reranker-v2-m3，约 6.5GB，不进镜像）
│   ├── Dockerfile               #   python:3.13-slim，非 root；默认 pip 装依赖（见文件头两种方式）
│   └── pyproject.toml           #   ⚠️ agent/ 下暂无 uv.lock（根 uv.lock 属于根项目）
├── frontend/                    # React 前端
│   ├── src/                     #   api/ pages/ components/ stores/
│   ├── vite.config.ts           #   dev 端口 3000，/api 代理到 localhost:8080
│   ├── dist/                    #   构建产物（nginx 托管）
│   └── Dockerfile               #   node:22-alpine 构建 → nginx:1.27-alpine 运行
├── deploy/                      # 部署产物
│   ├── docker-compose.yml       #   六服务编排（healthcheck + depends_on 顺序）
│   ├── nginx.conf               #   前端站点配置（SPA 回退 + /api 反代 + SSE 不缓冲）
│   └── RUNBOOK.md               #   运维手册（端口表/启停/排障/备份）
├── .env.example                 # 环境变量模板（含中文注释与安全提示）
├── .gitignore                   # 忽略规则：.env / 模型 / 依赖 / 日志 / 临时脚本
│                                #   （旧单体 src/ 也已排除，见下）
├── .dockerignore                # 构建上下文裁剪（排除模型/venv/node_modules）
├── pyproject.toml / uv.lock     # 根级 uv 工程（Phase 早期脚本用）
├── progress.md                  # 进度日志 + 「落地级优化」总表与各项实测数据
├── task_plan.md                 # 阶段计划、决策记录（D1–D7）、最终验收清单
├── findings.md                  # 旧系统缺口、关键事实、踩坑与解法（排障先看这个）
├── tmp/                         # 验证脚本与临时载荷（不进镜像）
│   ├── e2e_verify.py            #   全链路端到端（建岗→上传→筛选→反馈→面试）
│   ├── verify_idempotent.py     #   幂等缓存（重筛零 LLM、分数一致、结果不重复）
│   ├── verify_metrics.py        #   双端 /metrics 必填指标 + 直方图不变量 + 命名规范
│   ├── verify_job_overrides.py  #   岗位级配置（校验/生效/分数随权重变化）
│   ├── verify_job_ui.py         #   真实浏览器改岗位配置 → 后端落库
│   ├── bench_parse.py           #   解析性能基准（端到端 + 分阶段指标）
│   ├── dev_stack.py             #   一键拉起/检查开发依赖容器（mysql/redis/chroma）
│   └── browser_check.py 等      #   登录/前端模块的浏览器（Edge CDP）验证脚本
└── docs/REQUIREMENTS_V5.md      # 需求与验收说明
```

---

## 四、启动方式

### 方式 A：本机开发模式（推荐日常开发，热重载友好）

开发端口与容器内端口不同，注意区分：**MySQL 13306、Chroma 18001**（宿主 3306 被本机 MySQL 占用）。

```bash
# 前置：Python 3.13、Go 1.24+、Node 20+ 已安装
# 依赖组件（MySQL 13306 / Redis 6379 / Chroma 18001）用容器单独起最省事：
docker run -d --name mysql-rec  --restart unless-stopped -p 13306:3306 -e MYSQL_ROOT_PASSWORD=password \
  -e MYSQL_DATABASE=recruitment -e TZ=Asia/Shanghai mysql:8.0
docker run -d --name redis-rec  --restart unless-stopped -p 6379:6379  redis:7-alpine
docker run -d --name chroma-rec --restart unless-stopped -p 18001:8000 chromadb/chroma:1.0.15

# ① backend（Go，8080）——启动时自动跑内嵌迁移，无需手工建表
cd backend
cp ../.env.example .env      # 或手写 backend/.env：见下方"环境变量表"
export GOPROXY=https://goproxy.cn,direct   # 国内必须
go build -o server ./cmd/server
./server                     # 读取 backend/.env（已存在的环境变量优先）
curl -s http://localhost:8080/readyz       # 期望 checks: mysql/redis/agent 全 ok

# ② agent（Python，8001）
cd agent
uv sync                      # 或 pip install -e .（国内用华为云/清华源）
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
curl -s http://localhost:8001/healthz      # 期望 status=ok, checks.embedder=true（预热完成）

# ③ frontend（React，3000，vite 代理 /api → http://localhost:8080）
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev -- --host 0.0.0.0   # 打开 http://localhost:3000
```

> **开发依赖容器自带 `--restart unless-stopped`**：Docker Desktop 重启后会自动恢复。
> 若容器被停掉（表现为"页面能开、接口在，但登录/注册等一切数据库操作失败"），执行
> `agent/.venv/Scripts/python.exe tmp/dev_stack.py up` 一键恢复并等待端口就绪；
> 想确认状态用 `tmp/dev_stack.py status`。

> **本机开发的 `agent/.env` 与 `backend/.env` 关键差异**（容器内拓扑换成 localhost 拓扑）：
> `DATABASE_URL` 用 `localhost:13306`、`REDIS_URL` 用 `localhost:6379/0`、
> `AGENT_BASE_URL=http://localhost:8001`、`CHROMA_HOST=localhost` + `CHROMA_PORT=18001`。
> 两端 `AGENT_INTERNAL_KEY` 必须一致（开发默认 `dev-internal-key`）。
> agent 的 `CHROMA_PORT` 在 `app/core/config.py` 里的默认值已是 **18001**（与开发约定一致），
> `.env` 里再显式写一遍更稳妥；容器内必须覆盖为 `8000`（见方式 B）。

### 方式 B：Docker Compose 一键启动（交付/演示/单机部署）

```bash
cp .env.example .env
# 必须修改：MYSQL_ROOT_PASSWORD / AGENT_INTERNAL_KEY / JWT_SECRET_KEY / LLM_API_KEY
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
docker compose --env-file .env -f deploy/docker-compose.yml ps   # 六服务均应为 healthy
```

启动后访问 **http://localhost:3000**。端口、日志、排障、备份的完整说明见 [`deploy/RUNBOOK.md`](deploy/RUNBOOK.md)。

容器拓扑速查：

| 服务 | 宿主端口 | 容器端口 | 说明 |
|---|---|---|---|
| frontend（nginx） | 3000 | 80 | 静态站点 + `/api/` 反代 backend:8080 |
| backend | 8080 | 8080 | 直连调试用（`/healthz`、`/readyz`） |
| agent | 8001 | 8001 | 直连调试用（`/healthz`，业务接口需 `X-Internal-Key`） |
| mysql | 13306 | 3306 | 宿主 3306 常被占用故用 13306 |
| redis | 6379 | 6379 | 限流/事件通道/锁 |
| chroma | 18001 | 8000 | 向量库（镜像锁 1.0.15） |

---

## 五、环境变量

> 完整模板见 [`.env.example`](.env.example)。下表列出**代码里真实读取**的变量与默认值；
> 标注「生产必填」的在 `APP_ENV=production` 时缺失会导致对应服务 fail-fast 拒绝启动。

### backend（`backend/internal/config/config.go`）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | `development` | `production` 时启用密钥校验并切 Gin Release 模式 |
| `HTTP_PORT` | `8080` | 监听端口 |
| `DATABASE_URL` | `root:password@tcp(localhost:3306)/recruitment?charset=utf8mb4&parseTime=True&loc=Local` | MySQL DSN（容器内改 `mysql:3306`） |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `AGENT_BASE_URL` | `http://localhost:8001` | AI 服务地址 |
| `AGENT_INTERNAL_KEY` | 开发兜底 `dev-internal-key` | **生产必填**，与 agent 一致 |
| `JWT_SECRET_KEY` | 开发兜底 `dev-only-secret-change-me` | **生产必填**（值为 `change-me` 也视为未配置） |
| `JWT_ISSUER` | `ai-recruitment-backend` | 签发方 |
| `JWT_EXPIRE_MINUTES` | `60` | token 有效期 |
| `RATE_LIMIT_GLOBAL_PER_MIN` | `100` | 全局限流（Redis 滑动窗口，按用户/租户，未登录按 IP） |
| `RATE_LIMIT_LOGIN_PER_MIN` | `10` | 登录/注册限流 |
| `RATE_LIMIT_UPLOAD_PER_MIN` | `20` | 简历上传限流 |
| `RATE_LIMIT_SCREEN_PER_MIN` | `5` | 触发筛选限流 |
| `UPLOAD_MAX_MB` | `10` | 上传大小上限（nginx `client_max_body_size` 需 ≥ 此值） |
| `SCREEN_WORKER_COUNT` | `4` | 筛选 worker 数 |
| `SCREEN_QUEUE_SIZE` | `64` | 筛选任务队列长度 |
| `SCREEN_TASK_TIMEOUT_SEC` | `300` | 单任务超时（agent HTTP 客户端超时 = 本值 + 30s，保证到点能切断 NDJSON 流） |
| `SCREEN_BATCH_SIZE` | `0`（用默认页大小 200） | 每批送粗筛的候选人数；大租户可调小以降低单批内存与单批耗时 |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:8501` | 逗号分隔白名单 |

**筛选相关默认值（代码内，非环境变量）**：候选人分页加载页大小 200；结果落库为 upsert（同租户+岗位+候选人唯一）；
断点保留 2 小时（进程内）；幂等缓存命中需「简历指纹 + 岗位配置指纹」双一致。

### agent（`agent/app/core/config.py`，pydantic-settings，读 `agent/.env`）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | `development` | `production` 时校验密钥并关闭 `/docs` |
| `LLM_API_KEY` | 空 | **生产必填**：DeepSeek Key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容地址 |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |
| `AGENT_INTERNAL_KEY` | 开发兜底 `dev-internal-key` | **生产必填**，与 backend 一致 |
| `CHROMA_HOST` | `localhost` | 容器内填 `chroma` |
| `CHROMA_PORT` | `18001`（代码默认值） | **本机开发 18001；容器内填 8000** |
| `EMBEDDING_MODEL_PATH` | `BAAI/bge-m3` | 本地存在 `models/bge-m3` 权重时自动改指向本地目录 |
| `RERANKER_MODEL_PATH` | `BAAI/bge-reranker-v2-m3` | 同上，自动优先 `models/bge-reranker-v2-m3` |
| `HF_ENDPOINT` | `https://hf-mirror.com` | 国内镜像（无本地权重时兜底下载源） |
| `WARMUP_MODELS` | `true` | 启动后**后台预热** embedder（不再让首个上传请求承担数十秒冷启动）；`RERANK_MODE=cosine` 时跳过 reranker 预热 |
| `VECTORIZE_IN_BACKGROUND` | `true` | 简历向量化转后台任务，上传响应只等「文本提取 + LLM 抽取」 |
| `RERANK_MODE` | `cosine` | 重排策略：`cosine`（用常驻 BGE-M3 做向量余弦，约 30–80ms/对）或 `cross_encoder`（BGE-reranker，准但 CPU 上约 3s/对） |
| `RERANK_PAIRS_FACTOR` | `2` | 送入重排的对数 = `max_candidates × factor`（cosine 模式下实际取 ≥4） |
| `RERANK_DOC_CHARS` | `400` | 单篇文档截断字符数（重排成本与长度强相关） |
| `RERANK_THRESHOLD_COSINE` | `0.55` | 余弦模式阈值（与 cross-encoder 的 0.4 不同量纲，故分模式配置） |
| `EMBEDDING_MAX_LENGTH` | `512` | 嵌入截断长度（简历 chunk 为 500 字符，避免默认 8192 的无谓 padding 计算） |
| `EMBEDDING_BATCH_SIZE` | `8` | 嵌入批大小 |
| `TORCH_NUM_THREADS` | `4` | torch 线程数；**多模型同进程时必须限制**，否则 CPU 超订会把重排拖慢一个数量级 |
| `LLM_MAX_CONCURRENCY` | `4` | 专家评估并发上限（保护上游限流） |
| `LOG_LEVEL` | `INFO` | 日志级别；`DEBUG` 会把 httpx/httpcore/openai 的逐请求日志打满（曾把单次筛选拖到百秒级） |
| `MCP_EMAIL_URL` / `MCP_CALENDAR_URL` | `http://localhost:9000` / `:9001` | mock MCP 面试工具（容器内用 `host.docker.internal`） |

> 兼容性提示：`EMBEDDING_MODEL_PATH` / `RERANKER_MODEL_PATH` 由 `app/core/config.py` 读取，
> 但会被 `_prefer_local_models()` **自动覆盖**——探测基准目录是
> `config.py` 上三级目录下的 `models/`（本机开发即 `agent/models/`，容器内即 `/app/models/`），
> 只要 `bge-m3` / `bge-reranker-v2-m3` 子目录里存在 `model.safetensors`、`pytorch_model.bin`
> 或 `model.safetensors.index.json`，就优先使用本地权重（国内规避 HF 镜像 403 的推荐路径）。
> 因此：**本机开发不必设置这两个变量**；`/app/models/...` 这两个值只对容器有意义。

### frontend

| 变量 | 说明 |
|---|---|
| （无运行时环境变量） | `vite.config.ts` 里 dev 端口 3000、代理 `/api → http://localhost:8080` 均写死在构建期 |
| 构建参数 | 国内 npm 源用 `npm install --registry=https://registry.npmmirror.com`；Docker 构建时由 `npm_config_registry` 指定 |

---

## 六、核心 API 摘要

统一前缀 `/api/v1`（业务接口），响应体约定 `{code, message, data}`；除注册/登录外均需 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/login` | 登录，返回 JWT |
| GET | `/api/v1/auth/me` | 当前用户信息 |
| POST | `/api/v1/jobs` | 新建岗位（`jd_text` → LLM 解析为结构化 JD） |
| GET | `/api/v1/jobs` | 岗位列表 |
| PUT | `/api/v1/jobs/:job_id/overrides` | **岗位级配置**（manager/admin）：`{weights:{专家:权重}, screen:{参数:值}}`；权重需属于该岗位专家组、为正、和为 1；检索参数走白名单，非法一律 400 |
| DELETE | `/api/v1/jobs/:job_id` | 删除岗位（manager/admin） |
| POST | `/api/v1/candidates/upload` | 上传简历（multipart `file`，支持 pdf/png/jpg） |
| GET | `/api/v1/candidates` | 候选人列表 |
| DELETE | `/api/v1/candidates/:candidate_id` | 删除候选人（manager/admin） |
| POST | `/api/v1/screen` | 触发筛选，202 异步受理，入参 `{job_id, max_candidates, query}` |
| GET | `/api/v1/screen/tasks/:task_id` | 查询筛选任务状态 |
| GET | `/api/v1/screen/tasks/:task_id/events` | **SSE** 推送筛选进度 |
| POST | `/api/v1/screen/tasks/:task_id/retry` | **失败任务续跑**：复用已完成候选人的结论，只补未完成部分；运行中任务返回 40902 |
| GET | `/api/v1/screen/match-results?job_id=` | 查询匹配结果 |
| POST | `/api/v1/feedback` | 提交反馈 `{candidate_id, job_id, feedback: suitable\|not_suitable}` |
| POST | `/api/v1/interview/draft` | 生成面试邀约邮件草稿 |
| POST | `/api/v1/interview/send` | 发送面试邀约（幂等） |
| POST | `/api/v1/interview/reply-intent` | 解析候选人回复意图 |

**agent 内部接口**（需请求头 `X-Internal-Key`，仅供 backend 调用）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/parse/jd` | JD 结构化解析 |
| POST | `/parse/resume` | 简历解析（multipart）；默认**向量化转后台**，响应含 `vector_pending` 标记 |
| POST | `/screening/run` | 执行筛选，**NDJSON 流式**返回；支持 `batches`（分批粗筛）与 `cached_reports`（幂等/断点复用） |
| POST | `/interview/draft` \| `/interview/send` \| `/interview/reply-intent` | 面试相关 |
| GET | `/healthz` | 健康检查（免内部密钥），`checks.embedder` 反映模型预热是否完成 |
| GET | `/healthz/metrics` | **Prometheus 文本格式指标**（免内部密钥） |

**运维与可观测端点**

| 端点 | 说明 |
|---|---|
| `GET /healthz`（backend） | 进程存活 |
| `GET /readyz`（backend） | 就绪：mysql / redis / agent 三项，任一失败返回 503 |
| `GET /metrics`（backend） | Prometheus 文本格式：HTTP（按路由模板）、筛选任务、缓存命中、成本/token、连接池、业务存量、任务存量 |
| `GET /healthz/metrics`（agent） | LLM 调用/耗时/token/成本、筛选任务与阶段耗时、解析阶段耗时、缓存命中、模型就绪状态 |

---

## 七、多 Agent 圆桌讨论机制

筛选不是"一个大模型打分"，而是**多角色独立评估 → 分歧检测 → 圆桌讨论 → 加权仲裁**四步，目的是压住单一模型的偏好与幻觉。

```
 候选人 × 岗位
      │
      ▼
 ① 混合粗筛：向量召回(BGE-M3) + BM25 关键词 + RRF 融合 → Top-K → Reranker 重排
      │
      ▼
 ② 多 Agent 独立评估（各角色并行，互不可见，避免相互带偏）
      │   按岗位类别（tech/management/design/general）动态选角与配权
      ▼
 ③ 分歧检测：计算各 Agent 总分的标准差 σ
      │   σ > 12  → 触发圆桌讨论
      ▼
 ④ 圆桌讨论（≤ 2 轮）
      │   · 各 Agent 陈述理由并看到他人结论，可修正自己的评分
      │   · 得分差 > 3 分才值得再辩一轮，超出 2 轮强制收敛
      │   · 引入「魔鬼代言人」角色专门唱反调（高分段 ≥ 80 分时重点质证）
      ▼
 ⑤ 仲裁加权汇总：interviewer 0.35 / skill_evaluator 0.35 / culture_fit 0.15 / stability_analyzer 0.15
      │   （设计类岗位权重不同：0.30 / 0.25 / 0.15 / 0.15 / 0.15，另含 visual_evaluator）
      ▼
 最终匹配结果 + 可追溯的讨论记录（谁改了口、为什么改）
```

**为什么这样设计**

- **独立评估**：先隔离再讨论，防止从众效应让所有 Agent 一开始就趋同。
- **σ > 12 才开会**：多数候选人分歧不大，无差别开圆桌纯属浪费 token 与时间；只在真正有争议时付这个成本。
- **≤ 2 轮 + 魔鬼代言人**：辩论收益递减，硬性收敛防止死循环；魔鬼代言人专治"一致看好"的盲区。
- **加权而非投票**：不同角色对最终结论的可信度不同（技术岗看重面试官与技能评估），用权重表达，而不是简单平均。

> 相关实现：`agent/app/agents/registry.py`（角色与权重）、`moderator.py`（分歧检测/仲裁）、
> `engine.py`（编排）；阈值参数见 `agent/app/core/config.py`（`debate_std_threshold=12.0`、
> `debate_max_rounds=2`、`debate_score_delta=3.0`、`devils_advocate_threshold=80.0`）。
>
> **权重可按岗位覆盖**：上述加权公式是「类别默认值」，可通过
> `PUT /api/v1/jobs/:job_id/overrides`（或前端「岗位管理 → 岗位详情 → 岗位级配置」）按岗位调整，
> 例如技术岗把技能评估权重从 0.35 提到 0.5。覆盖后**已缓存的精筛结论会自动失效并重算**
> （缓存键包含岗位配置指纹，避免"改了权重分数却不变"）。

---

## 八、落地级优化（性能与工程化实测）

本轮针对"能演示 → 能进客户环境跑"做了 7 项优化，均已用真实链路验证（明细与踩坑过程见
[`progress.md`](progress.md) 与 [`findings.md`](findings.md)）：

| 编号 | 模块 | 优化前 → 优化后（实测） | 关键手段 |
|---|---|---|---|
| O1 | 简历解析 | 单份上传 **8–11s → 2.1–2.2s**（−75%） | 解析移出事件循环；LLM 抽取 ∥ 向量化；启动后台预热模型；技能标签向量进程内缓存；嵌入 `max_length=512`；向量化转后台任务；响应不再回传简历全文 |
| O2 | 筛选链路 | 端到端 **150–290s（常超时失败）→ 16.9s** | 专家评估真并发（`to_thread` + 信号量）；重排默认改 BGE-M3 向量余弦（cross-encoder 在 CPU 上约 3s/对）；**限制 torch 线程数**（默认 14 线程 × 2 模型会把重排拖慢一个数量级）；日志降噪到 INFO |
| O3 | 幂等缓存 | 同岗位重筛 **LLM tokens 3689 → 0**、14.3s → 6.9s | 简历指纹（原文+结构化字段）+ 岗位配置指纹做缓存键；结果表加唯一键改 upsert，重筛不再堆重复行 |
| O4 | 大批量 | 去掉 **200 人静默截断** | 候选人分页加载 + 分批粗筛 + 合并去重后统一重排；查询向量与 HyDE 跨批次共享 |
| O5 | 任务续跑 | 失败后只补未完成部分 | 逐候选断点（2h TTL）+ `POST /tasks/:id/retry` + 前端「续跑（复用已完成）」按钮 |
| O6 | 可观测性 | 从"只能翻日志"到双端 `/metrics` | HTTP/任务/LLM 成本与 token/缓存命中率/连接池/业务存量；直方图不变量有测试保障 |
| O7 | 岗位级配置 | 权重与检索参数从硬编码变为按岗位可配 | `jobs.weights_override` / `screen_overrides`（JSON 列）+ 服务端校验 + 前端配置入口 |

**解析耗时构成（优化后实测）**：文本提取 0.16s · LLM 抽取 2.39s（当前唯一瓶颈，约占 90%）·
技能标准化 0.7s · 向量化 1.5–3.3s（后台异步完成，不占响应）。

**筛选耗时构成（3 候选，实测 12.6–16.9s）**：粗筛约 5s（查询嵌入 1.6–2.5s + Chroma 0.1–0.5s + 重排约 50ms）+
每候选精筛约 2–5s（4 位专家并行）。

> 默认值是"CPU 部署"取向：重排用向量余弦、`TORCH_NUM_THREADS=4`、跳过 cross-encoder 预热。
> 有 GPU 时把 `RERANK_MODE=cross_encoder` 打开可换更高精度。

---

## 九、测试

```bash
# backend：Go 单测（jwtutil / password / 调分边界 / 指纹 / 指标 / 断点合并 / 候选人分页集成测试）
cd backend && go test ./...

# agent：pytest（Windows 本地虚拟环境在 agent/.venv）
cd agent && .venv/Scripts/python.exe -m pytest tests/ -q

# frontend：类型检查 + 构建（也是 CI 的前端质量门）
cd frontend && npm run build
```

当前基线（2026-09-12）：**Go 6 个包全过、agent 34 项全过**。其中新增的"钉死不变量"类测试值得注意：

| 测试 | 防的是什么 |
|---|---|
| `agent/tests/test_hard_filter.py` | 技能词边界（`Java` 不得命中 `JavaScript`）、年限不硬编码年份 |
| `agent/tests/test_engine_parallel.py` | 专家评估必须并发（改成串行会直接失败） |
| `agent/tests/test_metrics.py` / `backend/internal/pkg/metrics/metrics_test.go` | 直方图不变量（bucket 单调不减、`+Inf == _count`）、`_total` 命名规范 |
| `agent/tests/test_job_overrides.py` | 岗位权重解析/回退、参数白名单、模式与阈值一致性、contextvars 隔离 |
| `backend/internal/pkg/fingerprint/fingerprint_test.go` | 指纹稳定性（键顺序无关）与敏感性（内容/配置变更必须改变指纹） |
| `backend/internal/repository/candidate_paging_test.go` | 真实 MySQL 集成：分页无重复无遗漏、`LoadForScreening` 不再截断到 200（库不可达时自动 skip） |

### 端到端与专项验证脚本（真实 LLM + 真实向量库）

`tmp/` 下的脚本**必须在 Windows 侧用 agent 的 venv 解释器执行**（WSL 访问不到 Windows
进程绑在 127.0.0.1 的端口）：

```bash
# ① 全链路：登录 → 建岗(LLM 解析) → 传 3 份简历 → 筛选(SSE 事件透传断言) →
#    任务状态 → 反馈调分 → 面试草稿 → 回复意图
agent/.venv/Scripts/python.exe tmp/e2e_verify.py
#    事件原文落盘 tmp/screen_events.json；输出末尾应为「== 端到端验证完成 ==」
#    其中断言：rough_result/fine_start/agent_result/divergence/candidate_done/cost 的 payload 字段齐全，
#    且 done 事件由 backend 在结果落库之后发出（任务 status=succeeded）

# ② 幂等缓存：同岗位连筛两次 → 第二次 tokens=0、分数一致、match_results 不重复
agent/.venv/Scripts/python.exe tmp/verify_idempotent.py

# ③ 指标：双端 /metrics 必填指标齐全 + 直方图不变量 + 无双重 _total 后缀
agent/.venv/Scripts/python.exe tmp/verify_metrics.py

# ④ 岗位级配置：非法权重被拒(400) / 合法生效 / 分数随权重真实变化
agent/.venv/Scripts/python.exe tmp/verify_job_overrides.py

# ⑤ 前端配置 UI（真实浏览器 Edge CDP）：登录 → 岗位详情 → 改权重 → 保存 → 后端落库
agent/.venv/Scripts/python.exe tmp/verify_job_ui.py

# ⑥ 解析性能基准：端到端上传耗时 + agent 分阶段指标（extract/llm/skills/向量化）
agent/.venv/Scripts/python.exe tmp/bench_parse.py

# ⑦ 开发依赖容器一键恢复（Docker Desktop 重启后容器被停掉时用）
agent/.venv/Scripts/python.exe tmp/dev_stack.py up     # 或 status / --fix-policy

# ⑧ 前端 dev + 代理：11 个模块转译 200 + /api/v1/auth/login 经 vite 代理成功 + 列表非空
agent/.venv/Scripts/python.exe tmp/frontend_verify.py

# ⑨ 直连 agent 排查 NDJSON 原始事件（绕过 backend）
agent/.venv/Scripts/python.exe tmp/agent_probe.py
```

强制触发多 Agent 圆桌讨论（默认阈值 σ>12，日常真实简历往往不触发）：

```bash
# Windows PowerShell：把分歧阈值临时降到 2，让任何评分差异都进入讨论
$env:DEBATE_STD_THRESHOLD='2'; cd agent; .venv/Scripts/python.exe -m uvicorn app.main:app --port 8001
# 跑 ① 后应看到 discussion 事件（每轮每个专家一条 turn）与 convergence=converged
```

> **验证环境的两个坑（省时间）**
> 1. **WSL 给 Windows 程序传环境变量不可靠**：`VAR=1 ./x.exe` 实测程序读到的是默认值。
>    要调参请写进 `backend/.env` / `agent/.env`，**并在启动日志里确认生效**
>    （backend 启动会打印 `screening config batch_size=... timeout_sec=...`）。
> 2. **PowerShell 管道会把中文变成 `?`**：脚本结论建议落盘成 UTF-8 JSON，再由 WSL 侧读取。

---

## 十、常见问题排查（FAQ）

**1. agent 启动时从 HuggingFace 下载失败 / 403**

国内直连 HF 基本不可用，`hf-mirror.com` 也可能 403。**推荐路径：用本地模型目录**。
把 `bge-m3` 与 `bge-reranker-v2-m3` 完整权重放到 `agent/models/` 下两个同名子目录，
`_prefer_local_models()` 会自动优先本地权重，不再联网（判断依据：目录里存在
`model.safetensors` / `pytorch_model.bin` / `model.safetensors.index.json`）。
容器场景通过 `AGENT_MODELS_DIR` 只读挂载到 `/app/models`，镜像内不含模型。

**2. Chroma 连接失败 / collection 报错**

先确认镜像版本是 **`chromadb/chroma:1.0.15`**：Python 客户端（chromadb 1.5.x）与 0.5.x 服务端
API 不兼容，版本错配的典型表现是 agent `/healthz` 的 `checks.chroma = "fail"`、日志 404/500。
再确认端口：容器内 `CHROMA_PORT=8000`，本机开发 `CHROMA_PORT=18001`（`config.py` 默认值已对齐 18001）。

**3. 用 curl 发中文 JSON 出现乱码 / 后端报 JSON 解析失败**

Windows 终端与 WSL 编码不一致导致，别直接 `-d '{"jd_text":"中文"}'`。
把 JSON 写成 UTF-8 文件再发：

```bash
cat > /tmp/jd.json <<'JSON'
{"jd_text": "招聘高级后端工程师，熟悉 Go 与 MySQL"}
JSON
curl -X POST http://localhost:8080/api/v1/jobs \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @/tmp/jd.json
```

**4. Redis 不可用会怎样**

- backend **启动时** Redis 连不上会直接退出（`redisclient.Connect` 内含 PING 校验），
  容器场景由 `depends_on: condition: service_healthy` 保证顺序。
- backend **运行中** Redis 挂掉：限流中间件**降级放行**并打 warn
  （`rate limit backend unavailable, allowing request`），即限流失效、请求照常通过；
  但筛选任务状态/SSE 事件通道、反馈幂等、分布式锁等依赖 Redis 的能力会失败并返回 5xx
  （502「下游服务不可用」特指 AI/下游服务不可达）。
- 影响面：`/readyz` 的 `checks.redis` 变为 `fail`（整体 503），应把它接入监控告警。

**5. SSE 页面一直没有进度输出**

排查顺序（详见 RUNBOOK 5.4）：Redis 通道里有没有消息 → `curl http://localhost:8080/readyz` 三项是否全 ok
→ `curl http://localhost:8001/healthz` 是否 ok → nginx 是否漏了 `proxy_buffering off`（改完 `restart frontend`）。
可以直连 8080 用 `curl -N -H "Authorization: Bearer <token>" .../events` 对比，快速区分是代理问题还是后端问题。

**6. 端口冲突**

宿主 3306 常被本机 MySQL 占用，所以项目开发统一用 **13306**；Chroma 宿主侧用 **18001**（容器内 8000）。
冲突时改 `.env` 的 `MYSQL_PORT` / `CHROMA_PORT` 即可，容器内互访地址不受影响。

**7. 上传第一份简历特别慢 / 筛选偶发几百秒**

- 首份慢是**模型冷启动**（BGE-M3 加载约 29s）：默认已开启后台预热，`/healthz` 的 `checks.embedder`
  为 `true` 后才算就绪；重启 agent 后稍等再上传即可。
- 筛选异常慢先看 agent `/healthz/metrics` 的阶段耗时：`screen_stage_seconds{stage="rerank"}` 若达数十秒，
  说明在跑 cross-encoder 且 CPU 超订——确认 `RERANK_MODE=cosine`、`TORCH_NUM_THREADS=4`（默认即是）。
- **别把 `LOG_LEVEL` 开成 `DEBUG` 跑生产**：httpx/httpcore/openai 的逐请求日志会把单次筛选拖到百秒级。

**8. 重复筛选很慢 / 改了岗位权重但分数没变**

- 重复筛选本应命中**幂等缓存**：second run 的 `cost` 事件应为 0、`screen_candidates_fine_total` 不再增长。
  没命中时看后端日志 `idempotent cache` 的 `miss_reasons`：`候选人无指纹`（历史数据，重新上传一次简历即可）、
  `简历已变更`、`无历史结论`、`岗位配置已变更`（正常，会重算）。
- 缓存键 = **简历指纹 + 岗位配置指纹**（JD/权重/检索参数）。所以改完配置后第一次筛选会重算，这是预期行为；
  如果**没改配置**却发现分数每次都不一样，那是 LLM 采样导致的正常波动（专家评估 temperature 非 0），
  不是缓存失效。

**9. 候选人超过 200 人会不会被截断**

不会。`LoadForScreening` 早先有 200 人硬顶（静默丢弃），现已改为分页加载 + 分批粗筛，
`rough_result` 事件会带 `batches` 字段与逐批进度消息；批大小可用 `SCREEN_BATCH_SIZE` 调整。

**10. 指标怎么看 / 要不要装 exporter**

不需要额外组件：backend `GET /metrics`、agent `GET /healthz/metrics` 直接输出 Prometheus 文本格式，
Prometheus 加两个 static_configs 即可抓取。建议优先告警的四条：
`screen_tasks_total{status="failed"}` 增长、`screen_task_seconds` P95 抬升、
`llm_cost_usd_total` 突增、`agent_model_ready{model="embedder"} == 0`（模型未就绪）。

---

## 十一、仓库与推送

- 远端仓库：**https://github.com/rookie-wy/HireFlow**（默认分支 `main`）
- 仓库根 = 本目录（三服务架构），**旧单体 `src/` 不纳入仓库**（已加 `/src/` 到 `.gitignore`；
  旧实现可从远端 `src/` 时代的提交或本地备份取回）

### 首次克隆

```bash
git clone https://github.com/rookie-wy/HireFlow.git
cd HireFlow
# 依赖与密钥都不在仓库里，克隆后必须自建：
cp .env.example .env                 # 填 MYSQL_ROOT_PASSWORD / AGENT_INTERNAL_KEY / JWT_SECRET_KEY / LLM_API_KEY
cp .env backend/.env                 # 本机开发用：把 mysql/redis/chroma 地址改成 localhost:13306 / :6379 / :18001
cp .env agent/.env                   # 至少要有 LLM_API_KEY / CHROMA_PORT=18001 / AGENT_INTERNAL_KEY
# 模型权重需另外获取（6.5GB，未入库）：放到 agent/models/bge-m3 与 agent/models/bge-reranker-v2-m3
```

### 提交与推送（⚠️ 环境要点）

```bash
# 在 WSL 里 git 连不上 github.com（本机实测 443 被拦），请用 **Windows 侧 git**：
"/mnt/f/Git/cmd/git.exe" -C "D:/PythonProject/PythonProject2" status
"/mnt/f/Git/cmd/git.exe" -C "D:/PythonProject/PythonProject2" add -A
"/mnt/f/Git/cmd/git.exe" -C "D:/PythonProject/PythonProject2" commit -m "feat: ..."
"/mnt/f/Git/cmd/git.exe" -C "D:/PythonProject/PythonProject2" push origin main
```

### 提交前自查（防止泄露隐私）

```bash
# 1) 确认没有 .env / 密钥 / 模型 / 依赖被暂存
git diff --cached --name-only | grep -E '\.env$|\.key$|\.pem$|\.log$|node_modules|\.venv|agent/models' && echo '⚠️ 需要处理'
# 2) 确认暂存内容没有真实 key 或本机绝对路径
git grep -InE 'sk-[A-Za-z0-9]{20,}|D:\\\\PythonProject|/mnt/d/PythonProject' --cached && echo '⚠️ 需要处理'
# 3) 看最终文件清单
git diff --cached --name-only | wc -l
```

> `.gitignore` 已覆盖：`.env` 与所有 `.env.*`（保留 `.env.example`）、`agent/models/`、
> `node_modules/`、`.venv/`、`frontend/dist/`、`*.log`、`tmp/`、简历样本 `resume_*.pdf`、`.idea/` 等；
> 若新增了含密钥的文件，请同步更新 `.gitignore` 再提交。

---

## 十二、相关文档

- [`deploy/RUNBOOK.md`](deploy/RUNBOOK.md) — 运维手册：端口表、启停重建、日志、故障排查、备份与卷清理
- [`progress.md`](progress.md) — 进度日志与「落地级优化」总表（每项含实测数据、设计理由、验证方式）
- [`task_plan.md`](task_plan.md) — 阶段计划、决策记录（D1–D7）、优化项与最终验收清单
- [`findings.md`](findings.md) — 旧系统缺口、关键事实、踩坑与解法（**排障优先看这个**）
- [`.env.example`](.env.example) — 环境变量模板与安全提示
- [`docs/REQUIREMENTS_V5.md`](docs/REQUIREMENTS_V5.md) — 需求与验收说明
