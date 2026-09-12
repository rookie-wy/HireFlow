# 任务计划：AI招聘Agent系统企业级重构（v4 → v5）

## 目标
将现有 Python 单体简历筛选系统重构为企业级三服务架构：
- **backend**（Golang/Gin）：业务中台 — API、JWT/RBAC、多租户、限流、筛选编排、反馈闭环、面试调度、SSE 进度
- **agent**（Python/FastAPI）：AI 能力服务 — LLM 网关、解析、嵌入、混合检索、**多Agent圆桌讨论精筛**
- **frontend**（React + TypeScript/Vite/AntD）：企业级前端
- 核心能力全保留；修复旧系统已知缺口（candidate_id 映射、真实加权公式、RBAC 未挂载、成本记录断链等）

## 决策记录
- D1: 三服务分离 — Go 独占 MySQL，Python 独占 ChromaDB/LLM/嵌入，Python 无状态（数据由请求传入）
- D2: 筛选用 NDJSON 流式返回，Go worker 消费并转发 Redis Pub/Sub，前端 SSE 实时看讨论过程
- D3: 服务间用 X-Internal-Key 静态密钥 + trace_id 贯穿
- D4: 多Agent讨论 = 独立评估 → 分歧检测(置信度加权均值+标准差) → 圆桌讨论(≤2轮+魔鬼代言人) → 仲裁(真实维度加权公式) ；讨论记录持久化
- D5: 稳定性维度新增规则型 StabilityAnalyzer（任期统计，零 LLM 成本），补齐 0.35/0.35/0.15/0.15 公式
- D6: 异步筛选用 Go goroutine 工作池 + Redis 状态（不引入 Celery）
- D7: 新代码放 backend/ agent/ frontend/ deploy/ docs/；旧 src/（v4 单体）仅在本地保留作参考，**不纳入新仓库**（已加 `/src/` 到 .gitignore，旧实现可从远端历史取回）

## 阶段
- [x] Phase 0: 规划 + v5.0 需求文档（docs/REQUIREMENTS_V5.md + 同步桌面文档）
- [x] Phase 1: Go 后端基础框架 + 认证鉴权模块（config/log/middleware/response/errors/health + users 表迁移 + register/login/JWT/RBAC）
- [x] Phase 2: Go 业务数据模块（jobs + candidates + 上传解析编排 + 仓储 + 迁移）
- [x] Phase 3: Python agent 服务基础框架（FastAPI 骨架/config/日志/LLM网关熔断重试成本/PII/内部鉴权）
- [x] Phase 4: Python 解析与向量化模块（JD解析、简历解析、技能匹配、分块嵌入写 Chroma）
- [x] Phase 5: Python 混合检索粗筛模块（硬过滤、BM25、稠密、RRF、重排、候选真实映射）
- [x] Phase 6: Python 多Agent圆桌讨论精筛模块（专家Agent + 分歧检测 + 圆桌讨论 + 魔鬼代言人 + 仲裁 + 讨论记录）
- [x] Phase 7: Go 筛选编排与反馈闭环（异步任务池、NDJSON→Redis→SSE、feedback、个性化加权、记忆/交互日志）
- [x] Phase 8: 面试调度模块（LLM 邮件草稿/回复意图 → Python，Go 幂等锁 + 发送编排，MCP email/calendar）
- [x] Phase 9: React TS 前端（登录、岗位、候选人、智能筛选+实时讨论视图、反馈、面试调度）
- [x] Phase 10: 部署与收尾（docker-compose、Dockerfile×3、.env.example、README、RUNBOOK、测试、文档终版）

## ✅ 状态（2026-09-12 下午收尾）
全部 11 个阶段完成。真实三服务联调通过（DeepSeek + 本地 BGE-M3 + Chroma + MySQL + Redis），
前端 `npm run build` 通过、Go `go vet`+`go test ./...` 通过、`docker compose config` 校验通过、
frontend 镜像构建成功（75.3MB）。
唯一未在本机跑完项：`backend` / `agent` 镜像构建与 `docker compose up` 全栈联调 —— 原因是
基础镜像 `golang:1.24-alpine` / `python:3.13-slim` 无本地缓存且镜像仓库被限流（详见 findings.md
「本机 Docker 构建限制」与 deploy/RUNBOOK.md 第 2 节的换源 retag 步骤）。

## 🚀 落地级优化计划（2026-09-12 启动，用户授权自主优化）

目标：从「能演示」推进到「能进客户环境跑」。每完成一个模块即覆盖更新本文件 + progress.md 的状态。

### 优化项总表（按依赖与收益排序）
| 编号 | 模块 | 问题（已核实） | 方案 | 验收标准 |
|------|------|---------------|------|---------|
| O1 | 解析性能 | 简历解析慢：单次上传 8–11s（实测）；模型冷启动、LLM 与向量化串行 | 分阶段埋点定位 → LLM 抽取与向量化并行 → 启动预热模型 → 参数调优 | 单份简历解析 P50 下降 ≥40%，且结果字段不缺失 |
| O2 | 精筛并发 | `asyncio.gather` 里跑的是**同步** LLM 调用，专家评估实际串行 | 每个专家 `asyncio.to_thread` 真并行；控制并发上限避免限流 | 4 专家阶段耗时接近单专家耗时；圆桌/仲裁逻辑不变 |
| O3 | 幂等缓存 | 同岗位重复筛选会把每个候选人**重复精筛**（每次 4+ 次 LLM 调用） | 按 (job_id, candidate_id, resume 指纹) 复用精筛结论，命中标注 cached | 重复筛选第二次 LLM 调用显著下降且结果一致 |
| O4 | 大批量 | `LoadForScreening` 硬顶 200 人，超出静默截断 | 分批粗筛 + 游标，全量候选人参与粗筛 | 500 人岗位候选人不被截断（可用测试数据验证） |
| O5 | 任务续跑 | 任务失败需整任务重跑 | 逐候选落库 + 断点续跑（重试仅补失败候选） | 人为打断后重跑只补未完成候选人 |
| O6 | 可观测性 | 无指标/无阶段耗时 | Prometheus 指标（HTTP/任务/LLM 成本/阶段耗时）+ `/metrics` | 指标可被抓取，含筛选中位耗时与成本 |
| O7 | 岗位级配置 | 权重与检索参数全局硬编码 | 岗位级权重/参数覆盖（DB 字段 + 请求透传） | 同一岗位可配权重，仲裁结果随之变化 |

### 执行顺序与状态（全部完成，2026-09-12）
- [x] O1 解析性能 —— 上传稳态 8–11s → 2.1–2.2s（详见 progress.md O1 详情）
- [x] O2 精筛并发 + 筛选提速 —— 150–290s → 16.9s（详见 progress.md O2 详情）
- [x] O3 幂等缓存 —— 重筛 LLM 归零、14.3s→6.9s、结果行不重复（详见 progress.md O3 详情）
- [x] O4 大批量分批粗筛 —— 分页加载 + 分批粗筛 + 统一重排，250 人集成测试通过
- [x] O5 任务续跑 —— 断点 + /retry + 前端按钮，合并语义单测 + 端到端复验
- [x] O6 可观测性 —— 双端 /metrics，一致性脚本通过（含直方图不变量校验）
- [x] O7 岗位级配置 —— 覆盖 + 校验 + 缓存按配置指纹失效 + 前端配置入口（浏览器实测）

### 最终验收（2026-09-12 收尾）
- 测试：**Go 6 个包全过、agent 34 项全过**
- 端到端：建岗 → 3 简历 → 筛选 `succeeded`（71.1/70.3/46.9）→ 反馈调分 71.1→81.76 → 面试草稿 → 回复意图
- 指标：`tmp/verify_metrics.py` 通过（backend 16 项 + agent 12 项必填指标齐全、直方图不变量成立、无双重 `_total`）
- 幂等：`tmp/verify_idempotent.py` 通过（第二次 tokens=0、分数一致、结果行不重复）
- 岗位配置：`tmp/verify_job_overrides.py` 通过（非法 400 / 合法生效 / 分数随权重变化）
- 前端：`tmp/verify_job_ui.py` 通过（浏览器配置 UI → 后端落库）

## 🧭 其他后续（低优先级，非阻塞）
1. 前端结果区分任务：已按 task_id 过滤「本次任务」，如需跨任务对比可加任务选择器
2. Vite 产物 1.28MB（gzip 405KB）单 chunk，可做 manualChunks 拆分
3. 面试历史/候选人回复时间线目前只做意图分析，可落库成会话视图
4. require_role 只覆盖 hr/manager/admin 三档，部门级数据权限未做（当前靠 tenant 隔离 + 岗位归属）

## 遇到的错误
| 错误 | 尝试次数 | 解决方案 |
|------|---------|---------|
| zerolog 链式方法为指针接收者，值返回不可链式 | 1 | logger 包加 L(ctx)/LG() 助手返回指针 |
| hf-mirror 下载 bge-m3 403 | 2 | ModelScope CLI 下载到 agent/models/，config 自动优先本地 |
| chroma 客户端 1.5.9(v2 API) vs 服务端 0.5.5(v1) 404 | 1 | 服务端换 1.0.15 镜像 |
| BM25Okapi 小语料 idf=0（N=2 df=1）全零分 | 1 | 换 BM25Plus（idf 恒正） |
| chroma 容器占宿主 8001，agent 服务绑定失败 | 1 | chroma 挪 18001，agent 占 8001 |
| python .env 路径少一级目录读不到配置 | 1 | config.py env_file 改为上三级（agent 根） |
| Git Bash 终端 curl 中文变 GBK 乱码 | 1 | 中文 JSON 载荷写入 tmp/*.json 文件后 --data-binary @file |
| 幂等键 defer Release 导致重复发送穿透 | 1 | 改为成功保留占位 24h、失败才释放 |
| Go SSE 事件只透传 result/report，前端拿不到候选/专家/讨论字段 | 1 | 整行解析 NDJSON，业务字段整体进 payload |
| agent 的 done 早于落库被透传，前端回查读到 running | 1 | agent done 只作空结果提示，backend 落库后再发 done |
| adjusted_score 浮点噪声（79.64000000000001） | 1 | ApplyBoost 两位小数四舍五入 + 单测 |
| nginx `proxy_pass http://backend:8080;`（无尾斜杠）会剥掉 /api 前缀 → 全量 404 | 1 | 改为 `proxy_pass http://backend:8080/;` |
| WSL 里 vite 报 `Cannot find module @rollup/rollup-linux-x64-gnu` | 1 | Windows 装的 node_modules 缺 Linux 原生包，`npm i --no-save @rollup/rollup-linux-x64-gnu @esbuild/linux-x64` |
| WSL 无法访问 Windows 进程的 127.0.0.1:8001/8080（只转发 0.0.0.0） | 1 | 验证脚本改用 Windows 版 python 执行（agent/.venv/Scripts/python.exe） |

