# 部署运维手册（RUNBOOK）

> 适用对象：AI 招聘 Agent 系统（Golang 后端 + Python AI 服务 + React 前端 三服务架构）
> 编排文件：`deploy/docker-compose.yml`；所有命令都在**仓库根目录**执行。

---

## 1. 容器与端口总表

### 1.1 宿主 ↔ 容器映射

| 服务 | 容器名 | 镜像 | 宿主端口 | 容器端口 | 用途 | 可调变量（.env） |
|---|---|---|---|---|---|---|
| frontend | ai-recruit-frontend | nginx:1.27-alpine（构建自 node:22-alpine） | 3000 | 80 | 前端静态站点 + `/api/` 反代到 backend | `FRONTEND_PORT` |
| backend | ai-recruit-backend | 本地构建（golang:1.24-alpine → alpine:3.20） | 8080 | 8080 | Go/Gin 业务中台，REST + SSE | `BACKEND_PORT` |
| agent | ai-recruit-agent | 本地构建（python:3.13-slim） | 8001 | 8001 | Python/FastAPI AI 能力服务 | `AGENT_PORT` |
| mysql | ai-recruit-mysql | mysql:8.0 | 13306 | 3306 | 业务库（宿主 3306 常被占用，故用 13306） | `MYSQL_PORT` |
| redis | ai-recruit-redis | redis:7-alpine | 6379 | 6379 | 限流计数、筛选任务事件通道、幂等/分布式锁 | `REDIS_PORT` |
| chroma | ai-recruit-chroma | chromadb/chroma:1.0.15 | 18001 | 8000 | 向量库（简历 chunk / 交互摘要） | `CHROMA_PORT` |

### 1.2 容器内互访地址（服务名，勿改成 localhost）

| 调用方 | 目标 | 地址 |
|---|---|---|
| backend → mysql | MySQL | `mysql:3306`（写在 `DATABASE_URL` 里） |
| backend → redis | Redis | `redis:6379`（写在 `REDIS_URL` 里） |
| backend → agent | AI 服务 | `http://agent:8001`（`AGENT_BASE_URL`） |
| agent → chroma | 向量库 | `CHROMA_HOST=chroma` + `CHROMA_PORT=8000` |
| frontend(nginx) → backend | 业务 API | `proxy_pass http://backend:8080` |
| agent → mock MCP | 邮件/日历工具（跑在宿主，**不在本编排内**） | `http://host.docker.internal:9000` / `:9001` |

### 1.3 探活端点

| 服务 | 端点 | 判定 | 说明 |
|---|---|---|---|
| backend | `GET /healthz` | 200 即存活 | 只反映进程状态，容器 healthcheck 用它 |
| backend | `GET /readyz` | 200/503 | 检查 mysql / redis / agent 三项，任一 fail 返回 503 + `status=degraded` |
| agent | `GET /healthz` | 200 | 返回 `{status, checks{llm_config, chroma, embedder}, service}`；`checks.embedder=false` 表示模型仍在预热（**此时别急着压测/上传**） |
| backend(指标) | `GET /metrics` | 200 | Prometheus 文本格式指标（HTTP/筛选任务/缓存/成本/token/连接池/业务存量），无需额外 exporter |
| agent(指标) | `GET /healthz/metrics` | 200 | Prometheus 文本格式指标（LLM 调用与成本、筛选与解析各阶段耗时、缓存命中、模型就绪） |
| mysql | `mysqladmin ping` | — | compose healthcheck |
| redis | `redis-cli ping` | — | compose healthcheck |
| chroma | `bash -c "exec 3<>/dev/tcp/127.0.0.1/8000"` | — | 镜像内无 curl/wget，用 bash TCP 探测 |
| frontend | `wget -qO- http://127.0.0.1/` | — | nginx 自身探活 |

> 为什么 backend 的 healthcheck 用 `/healthz` 而不是 `/readyz`：`/readyz` 含 agent 依赖，
> 若用它会形成「agent 未就绪 → backend 不健康 → frontend 起不来」的连锁等待。
> 依赖顺序由 `depends_on: condition: service_healthy` 显式表达，探针各管各的。

---

## 2. 首次部署

```bash
# 1) 准备环境变量（仓库根目录）
cp .env.example .env
#    必须修改：MYSQL_ROOT_PASSWORD / AGENT_INTERNAL_KEY / JWT_SECRET_KEY / LLM_API_KEY
#    改 MYSQL_ROOT_PASSWORD 时，DATABASE_URL 里的同名密码也要同步改（compose 不做嵌套替换）
openssl rand -hex 32   # 可用于生成 JWT_SECRET_KEY / AGENT_INTERNAL_KEY

# 2) 构建 + 启动全部六个服务
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build

# 3) 看健康状态（所有服务应为 healthy；agent 首次加载模型较慢，
#    healthcheck start_period 给了 180s）
docker compose --env-file .env -f deploy/docker-compose.yml ps
```

验证入口：

| 检查项 | 命令 / 地址 | 期望 |
|---|---|---|
| 前端页面 | http://localhost:3000 | 登录页正常渲染 |
| 后端就绪 | `curl -s http://localhost:8080/readyz` | `{"status":"ok","checks":{...全 ok...}}` |
| AI 服务 | `curl -s http://localhost:8001/healthz` | `{"status":"ok","checks":{"llm_config":true,"chroma":"ok"},...}` |
| 向量库 | `curl -s http://localhost:18001/api/v2/heartbeat` | `{"nanosecond heartbeat": ...}`（Python 客户端 chromadb 1.5.9 走 v2 API） |
| 端到端 | 前端登录 → 建岗位 → 传简历 → 触发筛选 | SSE 进度逐步出现，最终出 match_results |
| 指标可用 | `curl -s http://localhost:8080/metrics \| head` | 出现 `http_requests_total`、`screen_tasks_total` 等指标 |
| 模型就绪 | `curl -s http://localhost:8001/healthz` | `checks.embedder = true`（预热完成，可正常压测） |

> **构建阶段拉不到基础镜像（本机已实测的坑，2026-09-12）**
> `backend` 用 `golang:1.24-alpine`、`agent` 用 `python:3.13-slim`，这两个基础镜像本机此前未缓存。
> 若 `docker compose build` 长时间停在 `FROM ...` 不动（`docker system df` 的 Build Cache 不再增长），
> 基本都是**镜像仓库被限流**而不是 Dockerfile 有问题。判断与处理顺序：
>
> ```bash
> docker manifest inspect golang:1.24-alpine          # 能秒回说明仓库通；报 toomanyrequests 就是被限流
> docker images | findstr /i "golang python"          # 看基础镜像是否已在本地
> ```
>
> 1. 先确认 Docker Desktop 的 `registry-mirrors`（Settings → Docker Engine）里至少有一个可用；
> 2. 换一个可用镜像源手动拉一次并重打标签，再执行 `compose build`（Dockerfile 无需改动）：
>    ```powershell
>    docker pull <可用镜像源>/library/golang:1.24-alpine
>    docker tag  <可用镜像源>/library/golang:1.24-alpine golang:1.24-alpine
>    docker pull <可用镜像源>/library/python:3.13-slim
>    docker tag  <可用镜像源>/library/python:3.13-slim python:3.13-slim
>    ```
> 3. 已缓存基础镜像后，`compose build` 的重活就只剩 `go mod download`（走 goproxy.cn）与
>    `pip install`（torch / sentence-transformers / FlagEmbedding，体积大，首次构建慢属正常）。
>
> 备注：本机已验证 `deploy/docker-compose.yml` 通过 `docker compose config` 校验、
> `frontend` 镜像可正常构建（基础镜像 `node:22-alpine` / `nginx:1.27-alpine` 当时在缓存里）；
> `backend` / `agent` 镜像的构建在本机受限于上述注册表限流，未跑完。

> **Chroma 版本红线**：镜像必须锁 `chromadb/chroma:1.0.15`。
> Python 客户端（chromadb 1.5.x）与 0.5.x 服务端 API 不兼容，
> 版本错配的典型现象是 agent `/healthz` 里 `checks.chroma = "fail"`、
> 日志出现 404/500，或 `get_or_create_collection` 直接抛异常。

> **MySQL 密码与健康检查**：`mysql` 的 healthcheck 用 `mysqladmin ping -uroot -p"$MYSQL_ROOT_PASSWORD"`，
> 即密码参与探活。改 `.env` 里的 `MYSQL_ROOT_PASSWORD` 后必须 `--force-recreate mysql`
> 让容器重新注入变量；仅对**已初始化的旧数据卷**改密码不会改库里的实际密码，
> 需进容器执行 `ALTER USER 'root'@'%' IDENTIFIED BY '<新密码>';` 或参见 6.3 清理卷后重建。
> 同理，`DATABASE_URL` 里的密码必须与新密码保持一致，否则 backend 无法就绪。

---

## 3. 日常启停与重建

```bash
# 统一前缀，建议直接 alias
alias dc='docker compose --env-file .env -f deploy/docker-compose.yml'

dc ps                      # 状态总览（含 health 与端口）
dc up -d                   # 启动（已构建过镜像时）
dc up -d --build           # 重新构建镜像后启动（改了源码/依赖时用）
dc up -d --build backend   # 只重建单个服务
dc restart backend         # 重启单服务（配置来自 .env，改 .env 后需要 up -d 才生效）
dc stop                    # 停止全部（容器保留）
dc start                   # 启动已存在的容器
dc down                    # 停止并删除容器/网络（**保留数据卷**）
dc down -v                 # 连数据卷一起删（⚠️ 数据全丢，见第 6 节）
dc config                  # 校验 compose 文件与环境变量（不启动，排错第一步）
```

改完 `.env` 的正确姿势（`restart` 不会重新读 env_file）：

```bash
dc up -d --force-recreate backend agent frontend
```

---

## 4. 日志查看

```bash
dc logs -f --tail=200 agent            # 跟踪单个服务
dc logs -f --tail=200 backend frontend # 多服务
dc logs --since=10m backend            # 近 10 分钟
dc logs agent | grep -i "chroma\|bge\|traceback"   # 关键错误过滤

# 容器内直接排查
dc exec backend sh                     # backend 运行镜像是 alpine，有 sh/wget
dc exec agent bash                     # agent 是 debian-slim，有 bash/curl
dc exec mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" recruitment -e "show tables;"   # 表是否建好（7 张）
dc exec redis redis-cli keys 'rl:*'    # 看限流键
dc exec redis redis-cli keys 'screen:*'  # 看筛选任务事件通道
```

---

## 5. 常见故障排查

### 5.1 Chroma 版本错配

- 现象：agent `/healthz` 中 `checks.chroma = "fail"`；日志里 chromadb 客户端抛 404 / 500 / `KeyError`。
- 确认：`docker compose ... images | grep chroma`，必须是 `chromadb/chroma:1.0.15`。
- 处理：`dc up -d --force-recreate chroma`（改 tag 后先 `dc pull chroma`）。
- 附带：换版本可能造成既有 collection 维度/格式不兼容，必要时按 6.3 清理 `chroma_data` 后重建索引。

### 5.2 MySQL 端口冲突（bind: address already in use）

- 现象：`Error starting userland proxy: listen tcp4 0.0.0.0:13306: bind: address already in use`。
- 确认：`ss -lntp | grep 13306`（WSL/Linux）或 Windows 上 `netstat -ano | findstr 13306`。
- 处理：改 `.env` 的 `MYSQL_PORT=13307` 后 `dc up -d mysql`。
  注意：**宿主端口变了不影响 backend**，backend 走容器网络 `mysql:3306`。

### 5.3 模型挂载路径不对（agent 起不来 / 一直 degraded / 去下 HF）

- 现象：agent 日志出现 `_prefer_local_models` 未命中、开始从 hf-mirror 下载甚至 403；
  或 `Permission denied` / 目录为空。
- 确认三步：
  ```bash
  # ① .env 里的宿主侧路径（相对 deploy/ 或绝对路径）
  grep AGENT_MODELS_DIR .env
  # ② 宿主目录里必须有完整权重
  ls -la agent/models/bge-m3 | grep -E 'model.safetensors|pytorch_model.bin'
  ls -la agent/models/bge-reranker-v2-m3 | grep model.safetensors
  # ③ 容器内看到的挂载点
  dc exec agent ls -la /app/models/bge-m3
  ```
- 命中条件（`app/core/config.py`）：`/app/models/bge-m3` 与 `/app/models/bge-reranker-v2-m3`
  下存在 `model.safetensors` / `pytorch_model.bin` / `model.safetensors.index.json` 之一。
- 注意：Windows 路径不要写成 `D:\...`，在 WSL/Compose 里用 `/mnt/d/...` 或仓库相对路径。
- 注意：`HF_HOME=/app/model_cache` 是具名卷，**不能**指向只读的 `/app/models`。

### 5.4 SSE 没有输出（页面一直转圈、进度不动）

按以下顺序排查，逐层定位：

1. **Redis 事件通道里有没有消息**
   ```bash
   dc exec redis redis-cli keys 'screen:*'
   dc exec redis redis-cli monitor      # 触发一次筛选，观察是否有 publish/订阅流量
   ```
   没有消息 → 问题在 producer 侧：看 backend 日志的筛选 worker 与 agent `/screening/run`(NDJSON) 调用。
2. **backend 是否就绪**
   ```bash
   curl -s http://localhost:8080/readyz   # 三项必须全 ok
   dc logs --tail=100 backend | grep -i "screen\|events\|sse"
   ```
   `agent` 项 fail → agent 不可用，筛选根本不会开始。
3. **agent 是否健康**
   ```bash
   curl -s http://localhost:8001/healthz  # status 应为 ok；chroma fail 会直接影响筛选
   ```
4. **nginx 是否把响应缓冲掉了**（Redis/backend/agent 都正常但浏览器仍无输出时看这里）
   - 确认 `deploy/nginx.conf` 的 `/api/` 段存在：`proxy_buffering off; proxy_http_version 1.1;`
     `proxy_set_header Connection ''; proxy_read_timeout 600s;`
   - 改完 nginx.conf 需要重启前端容器：`dc restart frontend`（配置是挂载进去的）。
   - 直接绕过 nginx 验证，用于区分是代理问题还是后端问题：
     ```bash
     curl -N -H "Authorization: Bearer <token>" \
       http://localhost:8080/api/v1/screen/tasks/<task_id>/events
     ```
     直连有事件、经 3000 没有 → 一定是 nginx 配置问题。
5. 前端用的是 `fetch` 流式读取（`EventSource` 无法带 Authorization），
   若浏览器 DevTools → Network 里该请求被标记为 `pending` 且无增量数据，同样指向缓冲问题。

### 5.5 Redis 不可用会怎样（重要，与直觉不同）

| 时刻 | 行为 |
|---|---|
| backend **启动时** | `redisclient.Connect` 会 `PING` 校验，失败则进程直接退出（日志 `connect redis` + `redis ping:`）。depends_on 已保证启动顺序，所以正常不会发生。 |
| backend **运行中** Redis 挂掉 | 限流中间件**降级放行**（可用性优先）：日志出现 `rate limit backend unavailable, allowing request` 的 warn，请求不再被限流。 |
| backend 运行中 Redis 挂掉 | 依赖具体 Redis 操作的接口会失败：筛选任务状态/事件（SSE 读不到通道）、反馈幂等、分布式锁等，通常以 5xx 返回（下游/AI 能力不可用时才是 502「下游服务不可用」）。 |
| 其他 | `/readyz` 的 `checks.redis` 变为 `fail`，整体 503，可用于监控告警。 |

结论：**Redis 挂掉不会让登录取不到 token（JWT 无状态），但会让限流失效、筛选进度与事件通道断裂**。
生产上应把 `/readyz` 的 redis 项接入监控，而不是指望限流兜底。

### 5.6 中文 curl 载荷乱码 / JSON 解析失败

Windows 终端与 WSL 编码不一致时，`curl -d '{"jd_text":"中文"}'` 极易变形。统一做法：

```bash
# 把 JSON 写文件（UTF-8 无 BOM），再用 --data-binary 发送
cat > /tmp/jd.json <<'JSON'
{"jd_text": "招聘高级后端工程师，熟悉 Go 与 MySQL"}
JSON
curl -X POST http://localhost:8080/api/v1/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/jd.json
```

---

## 6. 数据备份与卷清理

### 6.1 MySQL 逻辑备份（推荐，跨版本可迁移）

```bash
# 备份（在宿主侧执行，输出到当前目录）
dc exec -T mysql mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" \
  --single-transaction --routines --triggers --default-character-set=utf8mb4 \
  recruitment > backup_$(date +%Y%m%d_%H%M%S).sql

# 恢复
dc exec -T mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" recruitment < backup_20250101_120000.sql
```

> 只需要业务数据、不需要索引时，可加 `--no-create-info` 等参数按需裁剪。
> 定时备份建议放宿主 crontab，并把 `.sql` 落到仓库外目录，避免被误清理。

### 6.2 Chroma 向量数据备份

```bash
# 方案 A：直接打包卷里的持久化目录（agent 写入，建议先停 agent 保证一致性）
dc stop agent
docker run --rm -v ai-recruitment_chroma_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/chroma_data_$(date +%Y%m%d).tar.gz -C /data .
dc start agent

# 方案 B：不做向量备份，直接重建索引（简历原文在 MySQL/对象存储里，可从业务侧重跑 embedding）
```

### 6.3 卷清理（⚠️ 破坏性操作）

```bash
dc down                 # 停容器，保留卷（安全）
docker volume ls | grep ai-recruitment   # 确认卷名：mysql_data / redis_data / chroma_data / model_cache

# 只清 Chroma（重建向量索引，保留业务库）
dc stop agent chroma
docker volume rm ai-recruitment_chroma_data
dc up -d chroma agent

# 只清 Redis（限流计数、事件通道、锁全部重置，业务库不受影响）
dc stop redis && docker volume rm ai-recruitment_redis_data && dc up -d redis

# 全量清理（业务数据一并删除，删除前务必先做 6.1 备份）
dc down -v
```

> `model_cache` 卷只存 HuggingFace 下载缓存，可随时删；
> 本地权重在宿主 `agent/models`（bind mount），删卷不会动它。

---

## 7. 上线前检查清单

- [ ] `.env` 已从 `.env.example` 复制，且 `MYSQL_ROOT_PASSWORD` / `AGENT_INTERNAL_KEY` / `JWT_SECRET_KEY` 全部换成随机值（≥32 字符）
- [ ] `DATABASE_URL` 里的密码与 `MYSQL_ROOT_PASSWORD` 一致
- [ ] `LLM_API_KEY` 为有效 DeepSeek Key，且账户有余额
- [ ] `APP_ENV=production`（backend/agent 会做密钥 fail-fast；同时 agent 关闭 `/docs`）
- [ ] `agent/models/bge-m3`、`agent/models/bge-reranker-v2-m3` 权重完整，`AGENT_MODELS_DIR` 指向正确
- [ ] chroma 镜像 tag 为 `1.0.15`
- [ ] `dc ps` 六服务全部 `healthy`；`/readyz` 三项 `ok`；agent `/healthz` 的 `checks.embedder = true`
- [ ] 已跑通一次端到端：登录 → 建岗 → 传简历 → 筛选出结果（SSE 有进度）→ 反馈 → 面试草稿
- [ ] `GET /metrics`（backend）与 `GET /healthz/metrics`（agent）都能抓到；已接入监控并配置告警
- [ ] `LOG_LEVEL` 保持 `INFO`（`DEBUG` 会因第三方 HTTP 日志把筛选拖慢一个数量级）
- [ ] 已配置 MySQL 定时备份；`.env` 未提交到版本库
- [ ] 对外暴露时：仅暴露 frontend 端口，8080/8001/13306/6379/18001 不要直接发布到公网

### 7.1 建议优先告警的四条指标

| 指标 | 含义 | 建议阈值（按规模调整） |
|---|---|---|
| `screen_tasks_total{status="failed"}` | 筛选任务失败累计 | 5 分钟内增长 > 0 即告警 |
| `screen_task_seconds`（P95） | 单任务耗时 | 持续 > 120s 告警（正常 3 候选约 12–17s） |
| `llm_cost_usd_total` | LLM 成本累计（agent 侧） | 突增或超日预算告警 |
| `agent_model_ready{model="embedder"}` | 嵌入模型就绪 | 持续 0 超过 5 分钟告警（比 `/healthz` 更早暴露"服务活着但不能干活"） |

排障时优先看的辅助指标：`screen_cache_hits_total` / `screen_cache_misses_total`（缓存是否在起作用）、
`screen_tasks_inflight`（是否堆积）、`mysql_pool_in_use` / `redis_pool_open`（连接池是否打满）、
`parse_stage_seconds{stage="llm"}` 与 `screen_stage_seconds{stage="rerank"}`（慢在解析还是重排）。

### 7.2 幂等缓存与续跑（运维需知）

- **幂等缓存**：同岗位重筛时，若「简历内容 + 岗位配置（JD/权重/检索参数）」都没变，直接复用历史精筛结论
  （第二次筛选 LLM 成本为 0）。改岗位配置或重新上传简历会让对应缓存失效并自动重算，属预期行为。
- **失败续跑**：任务失败后可 `POST /api/v1/screen/tasks/:task_id/retry`（前端筛选失败提示条上也有「续跑」按钮），
  已完成的候选人不会重算。断点保存在 backend 进程内存中，**backend 重启后断点丢失**（最坏情况就是整任务重跑）。
