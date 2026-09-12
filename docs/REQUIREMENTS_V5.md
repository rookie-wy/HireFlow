# AI招聘Agent 系统需求文档

**版本**：v5.0（企业级重构版）
**日期**：2026-09-11
**前版**：v4.0 精简聚焦版（2026-08-15）

---

## 0. 修订结论（v4.0 → v5.0 一句话）

v4.0 完成了「垂直业务收敛」，v5.0 在保留全部核心能力的前提下完成**企业级语言栈迁移与架构升级**：业务中台迁至 **Golang**、AI 能力独立为 **Python Agent 服务**、前端升级为 **React + TypeScript**，并将精筛升级为**多 Agent 圆桌讨论（Round-Table Review）模块**——含分歧检测、魔鬼代言人机制与真实维度加权仲裁，全过程讨论记录可审计、可实时观测。

### v4 → v5 核心变化

| 维度 | v4.0 | v5.0 |
|------|------|------|
| 业务后端 | Python FastAPI（业务+AI 混杂） | **Golang (Gin)** 业务中台 |
| AI 能力 | 与业务同进程 | **独立 Python Agent 服务**（无状态、可独立扩缩容） |
| 前端 | Streamlit 过渡 | **React 18 + TypeScript + Ant Design** |
| 精筛 | 2~4 专家 Agent + 辩论仲裁（公式未接线） | **圆桌讨论**：独立评估 → 分歧检测 → 多轮讨论 + 魔鬼代言人 → 置信度加权仲裁（真实公式） |
| 进度观测 | 同步阻塞、无过程可见 | **NDJSON 流式 → Redis Pub/Sub → SSE**，前端实时观看 Agent 讨论 |
| 稳定性评估 | 无（公式里的 stability 是空悬维度） | 新增**规则型 StabilityAnalyzer**（任期/跳槽频率统计，零 LLM 成本） |
| 数据归属 | Python 直写 MySQL+Chroma | **Go 独占 MySQL；Python 独占 Chroma**，边界清晰 |
| 限流 | slowapi 内存存储（多副本失效） | Go + **Redis 滑动窗口**（分布式） |
| RBAC | 已实现未挂载 | **按路由强制挂载**（hr/manager/admin 权限矩阵） |
| 成本记录 | CostRepository 断链无调用方 | LLM 网关内置计量，**每次调用落 cost_records** |
| 检索映射 | BM25/Chroma 结果 candidate_id 占位符 | **候选真实 ID 全链路映射**（修复） |
| DB 演进 | 启动时幂等执行 SQL | **golang-migrate 版本化迁移** |

---

## 1. 项目概述

### 1.1 定位
面向企业 HR 团队的智能招聘助手：简历解析 → 混合粗筛 → **多 Agent 圆桌精筛** → 可解释推荐 → 反馈闭环。

### 1.2 核心价值（不变）
- 效率倍增：简历初筛从小时级降到分钟级
- 精准匹配：混合检索 + 多 Agent 评估
- 过程可信：可解释报告 + 原文证据引用 + **可审计的 Agent 讨论记录**
- 持续演进：反馈闭环 + 人才记忆复用

### 1.3 关键指标

| 指标 | MVP 目标 | 企业级目标 |
|------|---------|-----------|
| 简历解析准确率 | ≥ 90% | ≥ 95% |
| 人岗匹配 Top5 召回率 | ≥ 80% | ≥ 85% |
| 单简历端到端延迟 | < 20s（含讨论） | < 12s |
| 系统可用性 | ≥ 99% | ≥ 99.5% |
| 精筛 Agent 分歧收敛率 | ≥ 70%（2 轮内达成共识） | ≥ 85% |

---

## 2. 总体架构

```
                        ┌─────────────────────────────┐
                        │   frontend (React + TS)     │
                        │  :3000  AntD / ECharts      │
                        └──────────┬──────────────────┘
                                   │ HTTPS (JWT)
                        ┌──────────▼──────────────────┐
                        │   backend (Golang :8080)    │
                        │  业务中台：API/鉴权/RBAC/多租户 │
                        │  限流(Redis)/幂等/筛选编排      │
                        │  异步任务池 + SSE 进度推送      │
                        └───┬───────────────┬─────────┘
                 X-Internal-Key│               │
             ┌─────────────────▼──┐      ┌─────▼──────┐
             │ agent (Python      │      │ MySQL 8    │
             │ FastAPI :8001)     │      │ (Go 独占)   │
             │ LLM网关/解析/嵌入    │      └────────────┘
             │ 混合检索/圆桌讨论    │      ┌────────────┐
             └───┬──────────┬─────┘      │ Redis 7    │
                 │          │            │ (共享)      │
        ┌────────▼───┐  ┌───▼────────┐   └────────────┘
        │ ChromaDB   │  │ DeepSeek / │
        │ (Python独占)│  │ BGE-M3/    │
        └────────────┘  │ Reranker   │
                        └────────────┘
```

### 2.1 服务职责边界（强约束）

| 服务 | 独占资源 | 职责 | 禁止 |
|------|---------|------|------|
| backend (Go) | MySQL | 全部业务数据 CRUD、鉴权/RBAC/多租户、限流/幂等/分布式锁、筛选任务编排与状态机、反馈闭环、面试调度编排、SSE 推送、成本记录落库 | 直接调用 LLM/嵌入模型 |
| agent (Python) | ChromaDB、GPU/CPU 模型 | LLM 网关（熔断/重试/成本计量上报）、JD/简历解析、技能标准化、分块嵌入与向量检索、BM25/RRF/重排、**多 Agent 圆桌讨论**、邮件草稿/回复意图生成、PII 脱敏 | 直连 MySQL |
| frontend (TS) | — | 登录、岗位/候选人管理、智能筛选（实时讨论视图）、反馈、面试调度 | 直连 agent 服务 |

### 2.2 服务间通信协议
- **协议**：HTTP/1.1 JSON；筛选长任务用 **NDJSON 流式响应**（每行一个事件）
- **内部鉴权**：请求头 `X-Internal-Key`（环境变量注入），缺失/不匹配返回 401
- **链路追踪**：backend 生成/透传 `X-Trace-Id`，agent 服务原样透传并写入日志与事件
- **超时预算**：解析类 60s；筛选流式总预算 300s；面试草稿 30s

### 2.3 筛选任务数据流（异步 + 实时观测）

```
POST /api/v1/screen (202)
  → backend 创建 screening_tasks 记录，投递内存任务池
  → worker 调 agent /screening/run (NDJSON 流)
      每个事件(阶段/候选/Agent发言/讨论轮次) → Redis Pub/Sub (channel: screen:events:{task_id})
  → GET /api/v1/screen/tasks/{task_id}/events (SSE)
      订阅 Pub/Sub + 回放 history → 前端实时渲染讨论过程
  → 完成事件携带最终报告 → backend 落库 match_results + discussions
```

---

## 3. 核心流程（7 步）

1. **JD 解析** — 上传 JD 文本 → agent LLM 抽取硬性/软性要求/技能图谱/岗位类别 → Go 落库
2. **简历解析** — 上传 PDF/图片 → pymupdf 提取（OCR 后备）→ LLM 结构化 → PII 脱敏 → 技能标准化 → Go 落库 + agent 写向量库
3. **混合粗筛** — 硬性条件过滤（学历/年限/技能）→ BM25 + BGE-M3 双路召回 → RRF 融合 → BGE-Reranker → Top-N（候选真实 ID 全链路映射）
4. **多 Agent 圆桌精筛** — 专家独立评估 → 分歧检测 → 圆桌讨论（含魔鬼代言人）→ 置信度加权仲裁 → 综合报告（详见 §4）
5. **可解释报告** — 综合分 + 维度小分 + 推荐理由 + 原文证据引用 + 讨论记录
6. **人工反馈** — HR「合适/不合适」→ 个性化权重调整 + 交互日志 + 高潜人才沉淀
7. **面试调度** — LLM 生成邀请草稿 → 人工确认 → 幂等发送（邮件 + 日历）→ 回复意图分析

---

## 4. 多 Agent 圆桌讨论模块（核心设计）

### 4.1 设计目标
- **防单点偏见**：多视角独立评估，避免单一 Agent 的锚定效应
- **分歧即价值**：分歧不是噪声，是信号的来源——强制交换证据后收敛
- **成本可控**：无分歧时零讨论开销；讨论时只交换摘要不交换全文
- **过程可审计**：每轮发言、立场变化、仲裁依据全部持久化，前端可回放

### 4.2 参与角色

| 角色 | 类别适配 | 职责 |
|------|---------|------|
| InterviewerAgent（面试官） | 全类别 | 综合匹配度：经验、项目契合、成长潜力 |
| SkillEvaluationAgent（技能专家） | tech/design | 技能深度、工具熟练度 vs 技能图谱 |
| LeadershipAgent（领导力评估） | management | 团队管理、决策、视野 |
| VisualEvaluationAgent（作品评估） | design | 作品相似度（MCP 视觉检索，失败回退 LLM 文本评估） |
| CultureFitAgent（文化匹配） | 全类别 | 沟通、协作、适应性 vs 软性要求 |
| **StabilityAnalyzer（稳定性分析）** ★新 | 全类别 | **规则型（非 LLM）**：平均任期、跳槽频率、空窗期 → 0-100 分 |
| **ModeratorAgent（主持人）** ★新 | — | 分歧检测、轮次控制、魔鬼代言人指派、最终仲裁与推荐语 |
| **DevilsAdvocate（魔鬼代言人）** ★新 | 按需注入 | 当共识分数过高（≥80）时系统性唱反调，对抗群体乐观偏差 |

### 4.3 四阶段协议

**Stage 1 独立评估（并行）**
所有专家 Agent 并行评估，输出 `AgentEvaluationResult{score, dimension_scores, evidence[], confidence}`。

**Stage 2 分歧检测（Moderator，零 LLM 成本）**
- 置信度加权均值：`μ = Σ(score_i × conf_i) / Σ conf_i`
- 标准差 `σ ≤ 12` 且无极端分差 → **共识达成**，跳过讨论（省 60%+ token）
- `σ > 12` → 进入圆桌；另外 `min(scores) ≥ 80` 时额外注入魔鬼代言人

**Stage 3 圆桌讨论（≤2 轮）**
- 每位 Agent 收到**同伴摘要卡**（`{agent, score, 置信度, 维度分, 最强证据 1 条}`，不含全文，控制 token）
- 每轮必须输出立场：`maintain`（强化论证）或 `revise`（给出新分与理由），禁止无理由改分
- 魔鬼代言人视角：主动构造反例（如「技能列表宽泛但 JD 核心栈仅一条命中」「高跳槽率暗示留存风险」）
- **收敛判定**：`σ' ≤ 12` 或 分数变化 `Δ ≤ 3` 或 达到最大轮数

**Stage 4 仲裁（Moderator）**
- 真实维度加权公式（修复旧系统未接线问题），类别权重表：

| 类别 | 公式 |
|------|------|
| tech | `interviewer×0.35 + skill×0.35 + culture×0.15 + stability×0.15` |
| management | `interviewer×0.35 + leadership×0.35 + culture×0.15 + stability×0.15` |
| design | `interviewer×0.30 + skill×0.25 + visual×0.15 + culture×0.15 + stability×0.15` |
| general | `interviewer×0.50 + culture×0.30 + stability×0.20` |

- 每个参与 Agent 的最终分按 **confidence 加权**折叠进其所属维度
- Moderator 生成 ≤80 字推荐语 + 合并去重证据（按置信度取 Top5）
- 产出 `OverallReport` + 完整 `DiscussionTranscript`

### 4.4 讨论记录（可审计）
`DiscussionTranscript` 随 match_results 持久化：每轮每 Agent 的原文发言、立场（maintain/revise）、分数轨迹、收敛原因（consensus/converged/max_rounds）、魔鬼代言人触发标记。前端「讨论时间线」逐条回放。

---

## 5. 技术栈

| 层 | 选型 | 说明 |
|----|------|------|
| 业务后端 | Go 1.22+ / Gin / GORM / golang-jwt v5 / go-redis v9 / zerolog | 企业主流组合 |
| AI 服务 | Python 3.13 / FastAPI / litellm(DeepSeek) / FlagEmbedding(BGE-M3 + Reranker) / pymupdf / chromadb / rank_bm25 | 延续 v4 检索栈 |
| 前端 | React 18 / TypeScript / Vite / Ant Design 5 / ECharts / zustand | 企业级中后台标配 |
| 数据 | MySQL 8（Go 独占）/ Redis 7（共享：缓存/锁/限流/Pub-Sub/会话）/ ChromaDB（Python 独占） | |
| 部署 | Docker Compose（backend/agent/frontend/mysql/redis/chroma 六容器） | |
| 可观测 | zerolog 结构化日志（trace_id 贯穿）+ /healthz /readyz + 任务级事件流 | LangFuse 后置 |

---

## 6. 服务接口契约（摘要）

### 6.1 backend → agent（内部，X-Internal-Key）

| 端点 | 方法 | 说明 |
|------|------|------|
| /parse/jd | POST | JD 文本 → JobDescription JSON |
| /parse/resume | POST(multipart) | 简历文件 → CandidateProfile（含分块向量已写 Chroma） |
| /screening/run | POST | {job, candidates[], config} → **NDJSON 事件流**，最终事件含全部报告 |
| /skills/normalize | POST | 原始技能 → 标准技能标签 |
| /interview/draft | POST | 生成面试邀请邮件草稿 |
| /interview/reply-intent | POST | 候选人回复 → 意图分析(accept/propose_new_time/decline) |
| /healthz | GET | agent 服务健康（含 LLM/嵌入/Chroma 状态） |

### 6.2 frontend → backend（JWT）

| 端点 | 方法 | 权限 | 说明 |
|------|------|------|------|
| /api/v1/auth/register, /login | POST | 公开 | 注册/登录（JWT 60min） |
| /api/v1/jobs | GET/POST | hr+ | 岗位创建（触发 JD 解析）/列表 |
| /api/v1/candidates | GET | hr+ | 候选人列表 |
| /api/v1/candidates/upload | POST | hr+ (20/min) | 简历上传（白名单+魔数+10MB 校验） |
| /api/v1/candidates/{id} | DELETE | manager+ | 删除候选人 |
| /api/v1/screen | POST | hr+ (5/min) | 发起筛选（202 + task_id） |
| /api/v1/screen/tasks/{id} | GET | hr+ | 任务状态 + 结果 |
| /api/v1/screen/tasks/{id}/events | GET(SSE) | hr+ | 实时事件流（含讨论过程） |
| /api/v1/screen/match-results | GET | hr+ | 岗位匹配结果（含讨论记录） |
| /api/v1/feedback | POST | hr+ | 合适/不合适反馈 |
| /api/v1/interview/send | POST | hr+ | 发送面试邀请（幂等） |
| /api/v1/health | GET | 公开 | 聚合健康检查 |

### 6.3 RBAC 权限矩阵

| 能力 | hr | manager | admin |
|------|----|---------|-------|
| 岗位/候选人/筛选/反馈/面试 | ✓ | ✓ | ✓ |
| 删除候选人/岗位 | ✗ | ✓ | ✓ |
| 用户管理/成本报表 | ✗ | ✗ | ✓ |

---

## 7. 数据模型（MySQL，Go 独占）

沿用 v4 六表（字段兼容，可平滑迁移旧数据），新增 1 表：

| 表 | 说明 | 关键字段 |
|----|------|---------|
| users | 用户 | tenant_id, username, password_hash, role(hr/manager/admin) |
| jobs | 岗位 | jd_text, jd_json(JSON), job_category |
| candidates | 候选人 | resume_text, structured_json(JSON), embedding_id, UNIQUE(tenant_id,email) |
| match_results | 匹配结果 | overall_score, dimension_scores, recommendation_text, evidence, **discussion_json ★新** |
| interaction_log | 交互日志 | event_type, target_id, feedback, summary_vector_id |
| cost_records | Token 成本 | trace_id, model_name, tokens_prompt, tokens_completion, cost |
| **screening_tasks ★新** | 筛选任务 | job_id, status(pending/running/succeeded/failed), progress, error, result_summary |

所有表 `tenant_id` 隔离，高频查询索引覆盖 `(tenant_id, job_id)`。

ChromaDB collections（Python 独占）：`resumes`（1024 维，metadata: tenant_id/candidate_id/chunk_index）、`interaction_summaries`。

---

## 8. 非功能需求

| 类别 | 要求 |
|------|------|
| 安全 | bcrypt 密码、JWT HS256(60min)、内部服务静态密钥、文件上传魔数校验+10MB 上限、PII 脱敏（输出侧全量，输入侧身份证）、参数化 SQL |
| 多租户 | tenant_id 贯穿：JWT claims → Go GORM scope → agent 请求载荷 → Chroma metadata |
| 限流 | Redis 滑动窗口：login 10/min、upload 20/min、screen 5/min，全局 100/min |
| 幂等 | 面试发送 `idem:interview:{cid}:{jid}` NX+EX 86400；Lua 原子释放锁 |
| 容错 | LLM 熔断（5 失败/60s 熔断）+ 指数退避重试（≤3）+ 备用模型降级；嵌入失败降级规则匹配；OCR 失败降级 |
| 可观测 | trace_id 贯穿 Go→Python→LLM；结构化 JSON 日志；健康检查三件套（liveness/readiness/依赖状态） |
| 优雅停机 | Go/Python 均实现 SIGTERM 优雅退出（在途任务 drain） |
| 优雅降级 | Redis 不可用时限流降级放行+告警日志；LLM 失败时粗筛结果仍可用（精筛标记 failed_reason） |

---

## 9. 模块清单与重构进度

> 每完成一个模块更新本表。✅ 完成 · 🔨 进行中 · ⬜ 未开始

| # | 模块 | 范围 | 状态 | 产出 |
|---|------|------|------|------|
| 0 | 规划与需求文档 | 架构决策、接口契约、讨论模块设计 | ✅ | docs/REQUIREMENTS_V5.md |
| 1 | Go 基础框架 + 认证 | config/日志/中间件/统一响应/错误码/健康检查/迁移 + JWT/RBAC/用户 | ✅ | backend/ |
| 2 | Go 业务数据 | jobs/candidates CRUD、上传解析编排、仓储 | 🔨 | backend/internal/... |
| 3 | Python Agent 框架 | FastAPI 骨架、LLM 网关（熔断/重试/成本计量）、PII、内部鉴权 | ✅ | agent/app/core,infra |
| 4 | 解析与向量化 | JD/简历解析、技能标准化、分块嵌入 | ✅ | agent/app/services/parsing |
| 5 | 混合检索粗筛 | 硬过滤/BM25/稠密/RRF/重排、真实 ID 映射 | ✅ | agent/app/services/screening |
| 6 | 多 Agent 圆桌讨论 | 专家 Agent、分歧检测、讨论、魔鬼代言人、仲裁 | ✅ | agent/app/agents |
| 7 | Go 筛选编排与反馈 | 异步任务池、NDJSON→Redis→SSE、反馈闭环、个性化加权、交互日志 | ✅ | backend/internal/... |
| 8 | 面试调度 | 邮件草稿/回复意图、幂等发送、MCP 客户端 | ✅ | backend + agent |
| 9 | React TS 前端 | 登录/岗位/候选人/筛选实时讨论视图/反馈/面试 | 🔨 30%：基础设施/类型层/SSE客户端/登录store 已就位，页面待写 | frontend/ |
| 10 | 部署与收尾 | docker-compose、Dockerfile×3、.env.example、README、测试 | ⬜ | deploy/, README.md |

---

## 10. 后置项（企业规模化再上）

- LangFuse / OpenTelemetry 全链路追踪（当前结构化日志 + 事件流已覆盖 MVP 可观测需求）
- Celery/Kafka 任务队列（Go 工作池 + Redis 状态满足当前量级）
- Milvus / Elasticsearch（Chroma + 内存 BM25 满足 <10 万简历）
- vLLM 本地推理、多副本部署与 K8s 编排
- 面试多轮时间自动协商（当前：草稿 + 回复意图分析 + 人工确认）

---

## 附录 A：旧系统缺口修复对照

| 旧缺口（v4） | v5 修复 |
|-------------|--------|
| BM25/Chroma 结果 candidate_id 占位 | 全链路真实 ID 映射（§3 步骤 3） |
| 加权公式未接线（实为平均分） | 真实类别权重表 + confidence 折叠（§4.3 Stage 4） |
| hard_filter 仅学历 | 学历 + 年限 + 技能规则过滤 |
| RBAC 未挂载路由 | 全路由权限矩阵（§6.3） |
| 限流内存存储 | Redis 分布式滑动窗口 |
| CostRepository 断链 | LLM 网关内置计量自动落库 |
| 图编排歧义边 | Go 显式状态机编排 |
| 两份重复粗筛实现 | 单一 hybrid pipeline |
| 进程内 MemorySaver | 无状态设计（任务状态在 MySQL/Redis） |
| schedule 半桩 | 完整幂等发送 + 回复意图分析（§3 步骤 7） |
