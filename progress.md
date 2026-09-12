# 进度日志

## 🚀 落地级优化进度（每完成一个模块即覆盖更新本节）

| 编号 | 模块 | 状态 | 关键结果 |
|------|------|------|---------|
| O1 | 简历解析性能 | ✅ 完成 | 端到端上传稳态 **8–11s → 2.1–2.2s**（−75%）；重启后首份 10.45s → 7.55s |
| O2 | 精筛并发 + 筛选提速 | ✅ 完成 | 筛选端到端 **150–290s → 16.9s**；专家评估真并行；重排换策略 |
| O3 | 幂等缓存 | ✅ 完成 | 同岗位重筛 **LLM 调用归零**（tokens 3689→0），耗时 14.3s→6.9s，结果不重复 |
| O4 | 大批量分批粗筛 | ✅ 完成 | 去掉 200 硬顶：分页加载 + 分批粗筛 + 统一重排；250 人集成测试通过 |
| O5 | 任务续跑 | ✅ 完成 | 断点 + `/retry` + 前端按钮；断点合并语义 3 个单测全过，接口与零 LLM 复验通过 |
| O6 | 可观测性 | ✅ 完成 | 双端 `/metrics`：HTTP、筛选任务、LLM 成本/token、缓存命中、连接池、业务存量；一致性校验脚本通过 |
| O7 | 岗位级配置 | ✅ 完成 | 岗位级权重与检索参数覆盖 + 校验 + 缓存按配置指纹失效；实测分数随权重变化 |

### O1 详情（2026-09-12，含实测数据）
**基线（优化前）**：可观测指标缺失，只能靠日志推算——单份简历上传 8–11s；重启后首份 10.45s。

**优化动作（8 项，每项都有明确理由）**
1. `asyncio.to_thread` 包住解析：此前同步解析直接跑在事件循环里，**并发上传会互相排队**且拖住健康检查
2. LLM 抽取 ∥ 向量化并行：两者互不依赖（LLM 网络密集 / 向量化 CPU 密集），耗时由「相加」变「取大」
3. 启动后台预热模型：`warmup_models=true`，embedder 与 reranker **并行**加载（串行实测 28.9s+9.9s）
4. `/healthz` 增加 `checks.embedder`：可区分「服务活着」与「模型没加载完」
5. 技能标签向量进程内缓存：此前**每次上传都重新嵌入 18 个常量标签**
6. 嵌入参数显式化：`embedding_max_length=512`（避免默认 8192 token 的无谓 padding）、`embedding_batch_size=8`
7. 向量化转后台：`vectorize_in_background=true`，上传响应只等「提取+LLM」，粗筛有 BM25 兜底
8. 不回传简历全文：`raw_text` 字段从响应中剔除（back1 只取结构化字段）

**优化后分阶段实测（agent `/healthz/metrics`，3 份简历）**
| stage | avg | 说明 |
|-------|-----|------|
| extract（pymupdf） | 0.16s | 已可忽略 |
| llm（DeepSeek 抽取） | 2.39s | **当前唯一瓶颈（约 90% 墙钟时间）** |
| skills（规则+缓存标签） | 1.22s | 首次含标签向量嵌入，之后显著下降 |
| 后台向量化（不占用响应） | 1.5–3.3s | 异步完成，`vectorize_bg_total{status=ok}` 计数 |
| 端到端上传 | **2.15–2.19s** | 后端+网络+解析；首份 7.55s（含 caches 冷启动） |

**过程中发现并修复的真实缺陷**
- **FlagEmbedding 并发竞态**：`tokenizer.pad()` 收到 list → `AttributeError: 'list' object has no attribute 'keys'`，
  导致整个筛选任务 `agent 流式调用失败 ... context deadline exceeded`。
  修复：嵌入/重排各加一把**推理锁**（二者独立、互不阻塞），并对该错误特征做一次定向重试。
  根因是库内 `encode/compute_score` 共享 tokenizer 无并发保护，而本次新增的「后台向量化」引入并发。

**验收与回归**
- 三份简历端到端上传稳态 2.15/2.19s（较基线 −75%）
- 筛选回到 `succeeded`，15 个 SSE 事件透传断言全绿，反馈调分 70.3 → 80.84 正常
- agent 16 个测试通过；Go 测试通过
- 新增基准脚本：`tmp/bench_parse.py`（端到端 + 分阶段指标一次性输出）


## Session 2026-09-12（下午）：Phase 9 前端完成 + Phase 10 部署产物 + 三处真实缺陷修复

### Phase 9: React TS 前端 — ✅ 完成（构建 + 接口契约对齐）
- 新增：src/main.tsx（ConfigProvider zhCN + AntdApp + HashRouter）、src/App.tsx（路由 + 登录守卫）、
  src/components/AppLayout.tsx（侧边菜单/租户角色/退出）
- 新增页面 5 个：
  - Login.tsx：登录/注册双 Tab（租户 + 角色），登录态 zustand 持久化
  - Jobs.tsx：JD 文本域 → 创建即解析（硬性/软性要求 + 技能图谱 + 类别），列表/详情/删除，一键「去筛选」
  - Candidates.tsx：Upload.Dragger 多文件上传（pdf/png/jpg）→ 解析入库 → 列表/详情/删除
  - Screening.tsx（核心）：选岗位+入池人数 → POST /screen 202 → fetch 流式 SSE →
    实时视图（阶段进度/粗筛入池/专家评估卡片/分歧 σ/圆桌讨论时间线 Timeline）→ done 后结果卡片
    （排名、调分、维度条、推荐语、证据、专家标签、讨论回放）+ 👍👎 反馈即时重算调分 + 排序切换
  - Interview.tsx：选岗位+候选人+时间段 → LLM 草稿预览（可编辑）→ 选时间 → 幂等发送 → 回复意图分析
- types.ts/client.ts 按后端真实契约重写（payload 嵌套、discussion_json 含 agent_details、boost/adjusted_score）
- 验证：`npm run build`（tsc -b 严格模式 0 错误 + vite 3101 模块）通过

### Phase 10: 部署与收尾 — ✅ 产物完成
- deploy/docker-compose.yml（六服务 + 全部 healthcheck + service_healthy 依赖链 + 四命名卷）：`docker compose config` 校验通过
- backend/agent/frontend 三个 Dockerfile、deploy/nginx.conf、deploy/RUNBOOK.md、根 README.md/.env.example/.dockerignore
- docker build backend + frontend 已实测（见下）

### 本轮修复的真实缺陷（全部经运行验证）
1. **Go 事件透传丢失**：ScreeningEvent.Payload 只取 result/report，导致候选列表/专家名单/分歧统计/
   讨论发言/成本全部到不了前端 → 改为整行解析 NDJSON，type/progress/message 单独承载、其余业务字段整体进 payload
2. **done 与落库竞态**：agent 自己的 done 事件被直接透传，早于结果落库，前端收到 done 立刻回查读到 running
   → agent 的 done 被拦截（仅用于记录空结果提示），真正的 done 由 backend「落库 + 任务置 succeeded」之后发布
3. **调分浮点噪声**：adjusted_score 出现 79.64000000000001 → ApplyBoost 增加两位小数四舍五入 + 新增单测（6 用例）

### 端到端实测（真实 DeepSeek + 本地 BGE-M3 + Chroma，Windows 侧 python 驱动）
- 建岗解析 tech/6 条硬性要求/17 技能 → 上传 3 份简历（含新造 resume_chen.pdf：外包低增长画像）
- 粗筛 1/3 入池（李娜 Java 不匹配技能、陈晨 8 年经验通过硬过滤但重排分低于 0.4 阈值）
- 专家评估 interviewer 78 / skill 62 / culture 62 / stability 90 → σ=7.5 未触发讨论 → 仲裁 72.6
- 事件透传断言全绿：rough_result(candidates,pool_size) / fine_start(agents) / agent_result(result) /
  divergence(mean,std,needs_discussion) / candidate_done(report) / cost(usage)
- done 由 backend 落库后发布：任务 status=succeeded progress=100（竞态已消除）
- 反馈闭环：suitable → boost 0.1 → 72.6 → 79.64（两位小数）
- 面试：草稿生成（3 时间段）+ 回复意图（propose_new_time + 提取「周一上午10点」）
- 圆桌讨论强制验证：`DEBATE_STD_THRESHOLD=2` 重启 agent → 2 轮 6 条 discussion 事件、convergence=converged、
  payload keys=(candidate_id,turn) 全链路打通（恢复正常阈值后本轮 σ=7.5 自然不触发，与设计一致）

### 评审后修复的两个正确性缺陷（2026-09-12 晚）
1. **技能子串误判**（影响筛选正确性）：硬过滤与粗筛理由都用 `tag in skills / tag in resume_text`，
   导致 JD 要求「Java」时把「JavaScript」候选人放行（已实测复现 c1/c2 双双通过）。
   修复：新增 `skill_hit()` 单一入口——英文/缩写技能用**词边界正则**（Java 不匹配 JavaScript、
   C 不匹配 CSS、C++ / CI/CD / Node.js 按字面转义后加边界），中文技能保留子串匹配；
   硬过滤与 `_reasons()` 共用同一规则，避免「入池理由」与「过滤依据」互相矛盾。
2. **年限计算硬编码 2026**：`candidate_years()` 把「至今/空」一律按 2026 计，跨年后判定会悄悄偏移。
   修复：改为 `datetime.date.today().year`。
- 回归：新增 `agent/tests/test_hard_filter.py`（10 个用例覆盖词边界/中文技能/符号技能/年限/学历门槛），
  全量 16 passed；端到端复跑通过（入池 1/4，新增的前端候选人简历被正确排除）

### O2 详情（2026-09-12，含实测数据）

**现象**：O1 之后，筛选任务频繁 `agent 流式调用失败 ... context deadline exceeded`（backend 客户端 90s 超时），
实测一次筛选 **150–293s**，其中 `rough_result` 就要 153s。

**逐层定位（关键过程，避免误判）**
| 假设 | 验证方式 | 结论 |
|------|---------|------|
| 日志 DEBUG 洪泛拖慢（httpx/httpcore 逐请求写盘） | 关掉 DEBUG 后复测 | 有改善但不是主因（日志从数万行降到 4KB，耗时仍高） |
| Chroma 慢 | 单独计时 | 排除：query 0.05–0.4s |
| 嵌入慢 | 单独计时 | 排除：单条查询 0.33s |
| **重排慢** | 隔离环境用**真实输入**复现 | **确认**：cross-encoder 2 对 6.4s（≈3.2s/对），10 对 20s+；服务器里更恶化到 40s/2对 |
| **torch 线程超订** | 打印 `torch.get_num_threads()` | **确认主因**：默认 14 线程 × 2 模型共存 → 重排从 ~2s 恶化到 40s；模型加载还会把线程数重置回 14 |
| **嵌入/重排各持锁可并行** | 并行加载两模型后复测 | **确认**：两把独立锁会让两个模型同时抢 CPU，且触发 FlagEmbedding tokenizer 竞态 |

**修复动作**
1. **两模型共用一把推理锁**（`_model_infer_lock`）：既避免 tokenizer 竞态，又避免 CPU 上两模型互相饿死
2. **`torch_num_threads=4`**（默认 14 → 4），且**模型加载后再设一次**（库会把线程数改回默认）
3. **重排策略化**：新增 `app/services/screening/reranker.py`
   - `RERANK_MODE=cosine`（默认）：用已常驻的 BGE-M3 做向量余弦，一次批量编码 ≈ 30–80ms/对
   - `RERANK_MODE=cross_encoder`：BGE-reranker cross-encoder（准，但 CPU 上 3s/对，有 GPU 再用）
   - 余弦分数映射到 [0,1] 并与 cross-encoder 分数同量纲；阈值按模式分流（cosine 0.55 / cross 0.4）
   - 余弦模式候选面扩大到 `max_candidates×4`（成本极低，召回更好）
4. **专家评估真并发**：`evaluate` 改为 `evaluate_sync` + `asyncio.to_thread` + 信号量（`LLM_MAX_CONCURRENCY=4`）。
   此前 async 函数内部跑同步 LLM，`asyncio.gather` 实际串行，4 个专家 = 4 倍等待
5. **日志降噪**：默认 INFO（`LOG_LEVEL` 可调），httpx/httpcore/openai/urllib3 一律压到 WARNING
6. 重排输入瘦身：对数 `max_candidates×factor`、单篇 400 字符、查询 256 字符

**优化后实测**
| 指标 | 优化前 | 优化后 |
|------|-------|-------|
| 筛选端到端（3 候选） | 150–293s（常超时失败） | **16.9s** |
| 其中粗筛 | 153s | **约 5s**（dense 2.3s + chroma 0.4s + 重排 ~50ms） |
| 其中专家评估（4 专家） | ~12s（串行） | **~2 工程 5s**（并行，取最慢者） |
| agent 日志/次筛选 | 数万行（DEBUG 洪泛） | ~4KB |

**新增测试**：`agent/tests/test_engine_parallel.py`（2 例，用 sleep 假 LLM 断言并发度，
串行回归会直接失败）→ agent 测试 16 → **18 passed**

**验收**：端到端 `status=succeeded`，两个候选人分别 70.2 / 39.4 分，反馈调分 70.2 → 80.73 正常，SSE 事件全通。

### O3 详情（2026-09-12，含实测数据）

**问题**：同一岗位重复筛选时，每个候选人会被**完整重新精筛一遍**（4 个专家 + 推荐语 = 每次 5 次 LLM 调用），
`match_results` 也会为同一 (岗位, 候选人) 不断追加新行，结果表越滚越大。

**设计**
- 简历指纹 `profile_hash = sha256(简历原文 + 规范化结构化字段)[:32]`（技能数组排序，保证与 map 顺序无关）
- `candidates.profile_hash` + `match_results.profile_hash` 双写；迁移 `0002_idempotent_cache.up.sql` 顺带清理历史重复行并加
  **唯一键 `uk_job_candidate (tenant_id, job_id, candidate_id)`**
- 筛选时 backend 取该岗位既有结论，只把「指纹一致」的候选放进 `cached_reports` 传给 agent
- agent 命中缓存的候选**跳过全部 LLM 调用**，但仍产出 `OverallReport`（否则落库会漏人），
  并额外发 `candidate_done{cached:true}` 事件让前端可标注
- 结果落库改为 **upsert**（唯一键冲突则覆盖），重筛不再堆重复行

**实测（新建岗位 + 3 份简历，连筛两次）**
| 指标 | 第 1 次 | 第 2 次（应命中） |
|------|--------|------------------|
| LLM tokens | 3689 | **0** |
| LLM 成本 | $0.00156 | **$0.00000** |
| 耗时 | 14.33s | **6.93s** |
| 缓存命中 | 0 | 2/2（`candidate_done.cached=2`） |
| 分数一致性 | — | **完全一致**（82.6 / 50.1） |
| match_results 行数 | 2 | 2（不重复） |

**过程中发现并修复的真实缺陷**
1. `CandidateRepo.Upsert` 的**更新分支漏了新字段**：`Updates(map[...])` 是显式白名单，
   加库字段时只改结构体不会生效 → 「重新上传简历」后指纹仍为空。已在更新分支补 `profile_hash`
   （这类白名单写法必须在注释里标注"新增字段要同步加"）
2. 诊断日志里的切片越界（`c.ProfileHash[:8]` 遇到空串）导致 backend panic → 改为安全截断函数

**新增测试**：`backend/internal/pkg/fingerprint/fingerprint_test.go`（3 例：键顺序无关 / 内容变更敏感 / 长度稳定）

### O4 详情（2026-09-12，含验证数据）

**问题**：`CandidateRepo.LoadForScreening` 硬编码 `limit>200 → 200`，租户候选人超过 200 人时**静默丢弃**其余简历
（按 `created_at DESC` 只取最近 200），大岗位/校招场景直接漏人，且没有任何提示。

**设计**
- backend：`CountByTenant` + `ListPage(offset, limit)`（按 `created_at DESC, id ASC` 稳定排序，翻页不漏不重）；
  `LoadForScreening(limit>200)` 改为**按需分页取满**；筛选时按页组装 `batches` 传给 agent，
  内存占用与页大小同阶（不再一次性把全租户候选人读进内存）
- agent：载荷同时兼容 `candidates`（单批）与 `batches`（多批）；对每批做硬过滤 + 双路召回，
  按 `candidate_id` 合并去重（保留高分），最后**统一重排一次**（控制成本：cross-encoder 只对候选面做）
- 查询向量与 HyDE 改写跨批次共享（只算一次），避免每批重复嵌入查询
- 双路都空时退化为池内顺序（不漏人）；新增事件 `rough_result.batches` 与逐批进度消息

**验证**
| 项 | 证据 |
|---|---|
| 分批事件 | agent 单测：2 批 7 人 → 2 条进度事件、`pool_size=7`、`batches=2`、无重复 ID |
| 不再截断 | **真实 MySQL 集成测试**：造 250 名候选人 → 分页取到 250（无重复/无遗漏）、`LoadForScreening(300)` 返回 250（旧实现只会给 200） |
| 默认行为不变 | `LoadForScreening(0)` 仍返回一页（200），兼容旧调用 |
| 端到端无回归 | 3 候选人全链路 `succeeded`；O3 幂等复验：二次筛选 `tokens=0`、耗时 21.3s → 13.1s、分数完全一致 |

**新增测试**：`agent/tests/test_screening_flow.py::test_batched_screening_covers_all_candidates`、
`backend/internal/repository/candidate_paging_test.go`（真实库集成测试，库不可达时自动 skip，CI 无依赖也能过）

### O5 详情（2026-09-12，实现完成 / 复用路径验证受阻）

**问题**：筛选任务失败（agent 超时、上游抖动）后，已完成的候选人精筛结论（每人 5 次 LLM 调用）全部作废，
只能整任务重跑。

**实现**
1. **断点**：`ScreeningService.checkpoints`（进程内 `sync.Map` + 2h TTL）逐候选保存已完成的 `OverallReport`；
   任务成功即删除（结论已落 `match_results`，无需保留）
2. **续跑接口**：`POST /api/v1/screen/tasks/:task_id/retry`
   - 运行中任务拒绝续跑（40902）；失败/成功任务均可续跑
   - 新建任务，把原任务断点作为**初始幂等缓存**注入，agent 只重算"未完成或简历已变更"的候选人
   - 返回 `reused_candidates` 供前端提示
3. **前端**：筛选失败告警条上新增「续跑（复用已完成）」按钮；受理后自动订阅新任务的 SSE 事件流

**已验证**
| 项 | 证据 |
|---|---|
| 触发真实失败 | 把 `SCREEN_TASK_TIMEOUT_SEC` 配成 3s：任务确实 `failed`，错误=`agent 流式调用失败 ... context deadline exceeded` |
| 续跑接口 | `POST /retry` 返回 202 + 新 task_id；新任务 `succeeded`，3 条结果齐全 |
| 与幂等缓存协同 | 续跑任务的筛选阶段命中 **3/3** 幂等缓存、**零 LLM 调用**（说明"复用"链路本身是通的） |
| 回归 | 恢复默认配置后 O3 幂等验证复跑通过（21.3s → 13.7s、tokens=0、分数一致） |

**断点复用语义（确定性单测验证）**：新增 `internal/service/screening_checkpoint_test.go`（3 例）
1. 断点报告全部并入缓存，分数/推荐语/证据/`agent_details` 均不丢，`ProfileHash` 置空（="来自父任务断点，允许命中"）
2. 已在 DB 缓存中的候选人**不被断点覆盖**（保留带指纹的条目，避免绕过"简历是否变更"判断）
3. 空断点为 no-op

**端到端复验**：`/retry` 返回 202 + 新任务，新任务 `succeeded` 且筛选阶段命中 3/3 幂等缓存、**零 LLM 调用**。
`reused_candidates=0` 的原因是**失败点总在粗筛阶段**（粗筛约 5s，超时 3/4/8/9s 都在此期间中断，
没有任何候选人完成 → 断点为空），这解释了为什么历史上"整任务重跑"是常态。

**本轮修正的真实缺陷**
- `pageSize` 覆盖问题：`s.batchSize` 的优先级判断被旧代码覆盖（早先一次字符串替换失败），
  导致 `SCREEN_BATCH_SIZE` 配了不生效（启动日志 1、任务日志 200）。已修为
  `batchSize > maxPool > 默认页大小`，并保留启动日志便于核对。
- agent HTTP 超时与任务超时脱钩：`SCREEN_TASK_TIMEOUT_SEC` 到点时 NDJSON 流不会被打断
  （HTTP 客户端自带 90s 超时罩着），任务照跑到底。已改为 `任务超时 + 30s 余量`。

**同类改进点（已记录，未做）**：断点粒度目前是"候选级"——若某候选的 4 位专家已评估完、
但 `candidate_done` 之前失败，这 4 次 LLM 调用仍会白费。要做到"专家级"续跑，需要按
`(task_id, candidate_id, agent)` 增量落库，属于后续增强。

### 附带优化：按重排模式跳过 cross-encoder 加载（2026-09-12 本轮）
- **问题**：默认 `RERANK_MODE=cosine` 时，启动预热仍会加载 BGE-reranker cross-encoder
  （实测加载约 10s、常驻内存约 2.3GB），而 cosine 模式根本不用它。
- **修复**：`warmup()` 只在 `RERANK_MODE=cross_encoder` 时加载 reranker；
  否则设置 `agent_model_ready{model="reranker"} = 0` 并打印 `reranker warmup skipped`；
  cross-encoder 仍保留懒加载（切模式后首次调用自动加载）。
- **验证**：agent 日志 `reranker warmup skipped (RERANK_MODE=cosine)` → 仅用 29s 加载 embedder，
  `/healthz` 返回 `checks.embedder=true`（不再等 reranker），端到端筛选照常成功。

### O6 详情（2026-09-12，含验证数据）

**问题**：只有 zerolog 日志与零散 `/healthz`，没有指标。排障全靠翻日志（本会话早些时候 MySQL 掉线就是靠日志才发现），
也答不上"成本花了多少、缓存命中率多少、任务 P95 多久、队列积压多少"。

**实现（双端，零新依赖）**
| 侧 | 内容 |
|----|------|
| backend | 新增 `internal/pkg/metrics`（计数器/直方图/gauge + 采集时求值 gauge + Prometheus 文本导出）；`/metrics` 暴露；HTTP 中间件按**路由模板**打点（避免 UUID 造成标签爆炸） |
| backend 业务指标 | `screen_tasks{status}`、`screen_task_seconds`、`screen_candidates_fine`、`screen_cache_hits/misses`、`screen_retries`、`screen_retry_reused_candidates`、`screen_tasks_inflight` |
| backend 采集时 gauge | `screen_cost_usd`、`llm_tokens`、`match_results_stored`、`candidates_stored`、`screen_tasks_stored{status}`、MySQL/Redis 连接池、`process_uptime_seconds` |
| agent | LLM 网关打点：`llm_calls{model,status}`、`llm_call_seconds`、`llm_tokens{kind}`、`llm_cost_usd`；筛选加 `screen_tasks{status}`、`screen_task_seconds`、`screen_results{cached}`、`screen_discussion_rounds` |

**实测（`tmp/verify_metrics.py` 全绿）**
```
必填指标：backend 16 项 / agent 12 项，缺失 0 项
无双重 _total 后缀（0 处）；backend/agent 直方图不变式（bucket 单调 / +Inf=count）全部通过
backend: screen_tasks_total{status="succeeded"} 5 | screen_cache_hits_total 5 | screen_cost_usd 0.0509
         llm_tokens{kind="total"} 122803 | match_results_stored 53 | screen_retries_total 1
agent  : llm_calls_total{model="deepseek-chat",status="ok"} 12 | llm_cost_usd_total 0.00285
         screen_results_total{cached="false"} 4 | agent_model_ready{model="embedder"} 1
```

**本轮修掉的三个指标自身缺陷（都是"指标可信度"问题）**
1. **直方图分桶语义错**：Go 侧存区间计数却按累积渲染（bucket 值甚至大于 count）→ 统一为「区间计数 + 渲染时累积」
2. **Python 侧反向错**：存累积值又在渲染时累积 → 同样统一，并新增 pytest 把不变量钉死
3. **命名规范**：出现 `_total_total` 双后缀、`le` 值在 Python 侧未加引号（违反文本格式）→ 规范化并加回归测试

**新增测试**：`backend/internal/pkg/metrics/metrics_test.go`（4 例）、`agent/tests/test_metrics.py`（4 例，含直方图不变量与标签引号）

### O7 详情（2026-09-12，含验证数据）

**问题**：仲裁权重（`WEIGHTS_BY_CATEGORY`）与检索参数（`rag_top_k` / `rerank_threshold` / `rerank_mode` …）
全部全局硬编码。业务上"这个岗位更看重稳定性、那个岗位更看重技能"无法表达；
合规上审计问"分是怎么来的"时，只能回答"用的代码里的默认值"。

**实现**
| 层 | 内容 |
|----|------|
| DB | 迁移 `0003`：`jobs.weights_override` / `jobs.screen_overrides`（JSON，可空=沿用默认，既有行为不变） |
| backend | `PUT /api/v1/jobs/:job_id/overrides`（manager+ 可改）；**服务端校验**：权重键必须在岗位专家组内、值为正、和为 1；检索参数走白名单，未知键直接 400 |
| backend → agent | 筛选载荷带 `job.weights_override` / `job.screen_overrides` |
| agent 权重 | `registry.resolve_weights(category, override)`：岗位覆盖 > 类别默认；未覆盖的专家权重置 0（而不是悄悄掺默认值）；异常输入整体回退默认并告警 |
| agent 参数 | `HybridScreener._cfg()` 统一取值（岗位覆盖 > 全局配置）；白名单 + 类型转换，非法值忽略并告警；重排模式用 **contextvars** 传递会话覆盖，避免并发任务串味 |

**实测（`tmp/verify_job_overrides.py`）**
```
非法配置：未知专家 / 权重和≠1 / 权重非正 → 全部 HTTP 400（校验生效）
合法配置：{"interviewer":0.7,"skill_evaluator":0.3} + {"rag_top_k":12,"rerank_threshold_cosine":0.5} → 200
带覆盖筛选：eefae075 = 90.8，879e63ac = 42.0
清空覆盖后：eefae075 = 86.4（-4.4），879e63ac = 49.7（+7.7）  ← 权重真实影响仲裁
```

**验证过程中发现并修复的真实缺陷（重要）**
> **幂等缓存没把"岗位配置"纳入缓存键**：只比对简历指纹，导致改了权重后重筛仍复用旧结论——
> 现象是"配置保存成功、筛选也跑了，但分数一点没变"，非常容易被误判为"配置功能没生效"。
> 修复：新增 `match_results.config_hash`（迁移 `0004`），指纹覆盖 **JD + 权重 + 检索参数**；
> 缓存命中必须同时满足「简历指纹一致」+「配置指纹一致」，未命中原因也会区分"岗位配置已变更"。

**前端入口（避免"后端有功能、HR 看不到"）**
- `api.updateJobOverrides()` + 岗位详情弹窗新增「岗位级配置」区：4 个专家权重 + `rag_top_k` + 余弦重排阈值，
  带「保存岗位配置」「清除覆盖（恢复默认）」，仅 manager+ 可改（其余角色禁用并提示）
- **真实浏览器验证**（`tmp/verify_job_ui.py`）：登录 → 岗位页（表格 10 行）→ 打开详情（配置区块存在）
  → 填 `面试官 0.6 / 技能 0.4 / rag_top_k 15` → 保存 → **后端实际落库**
  `weights={'interviewer':0.6,'skill_evaluator':0.4} screen={'rag_top_k':15}`

**新增测试**：
- `agent/tests/test_job_overrides.py`（10 例：权重解析/归一化/非法回退、参数白名单与类型转换、模式与阈值一致、contextvars 隔离）
- `backend/internal/pkg/fingerprint/fingerprint_test.go::TestJobConfigChangesInvalidateCache`（配置指纹对权重/参数/JD 变化敏感、对键顺序不敏感）

### 🔴 现场故障：登录/注册数据库操作全失败（2026-09-12 晚，已修复）
- **现象**：前端点登录/注册报错；backend 日志出现 MySQL 连接失败
- **根因**：Docker Desktop 重启导致 `mysql-rec`/`redis-rec`/`chroma-rec` 三个容器被停
  （它们是 `docker run` 起的，**restart policy = no**，不会自恢复）；agent(8001) 进程也已停。
  后端进程没死，所以表现为「接口在，但一碰数据库就失败」
- **修复**：`docker start mysql-rec redis-rec chroma-rec` + 重启 agent；
  并 `docker update --restart unless-stopped mysql-rec redis-rec chroma-rec`（下次 Docker 重启会自动拉起）
- **预防**：新增 `tmp/dev_stack.py`（`up` / `status` / `--fix-policy`），一键拉起并等待端口就绪
- **复验**：`/readyz` 三项全 ok；浏览器真实交互回归「登录→/#/screening」「注册→/#/screening」均通过

### 配置修正
- agent/app/core/config.py：chroma_port 默认值 8001 → 18001（8001 是 agent 自身端口，原默认会自连）

### 登录演示相关修复（2026-09-12 傍晚追加）
4. **注册接口不返回 token**：`/auth/register` 只返回 role/tenant/username，前端注册 Tab 会直接写登录态 →
   `access_token` 为空、进主页被守卫踢回登录页（注册即登录是坏的）→ Go 端抽出 `issueToken()`，
   Register 与 Login 返回契约完全一致（已用真实浏览器「填表→提交」验证直达 `/#/screening`）
5. **antd 静态 message 告警**：`Static function can not consume context like dynamic theme` →
   新增 `src/api/notify.ts` 桥接层，由 `MessageBridge`（`App.useApp()`）注入实例，
   axios 拦截器与各页面统一走 `notifySuccess/notifyError/notifyWarning`，控制台已无该告警

### 真实浏览器验证（Edge headless + CDP，本轮新增）
- `tmp/login_e2e.py`：CDP 填表 + 点击提交（真实交互路径）→ 登录后 URL=/#/screening、侧边菜单四项齐全
- `tmp/register_e2e.py`：切换到注册 Tab（注意 antd 会把两个面板都留在 DOM，选择器必须限定 `.ant-tabs-tabpane-active`）
  → 新租户注册 → 直达 /#/screening
- `tmp/login_layout.py`：DOM 几何度量（卡片 420px 居中、三字段可见、无横向溢出、提交按钮=登录）
- `tmp/browser_check*.py` / `tmp/cdp_diag*.py`：CDP 排查脚本（保留作为排障参考）
- 截图目录：`tmp/shots/`（01-login / 03-after-login / 04-jobs 等）
- **踩坑记录**：hash 路由下 `Page.navigate` 不触发整页重载，store 只在模块加载时水合 localStorage，
  所以「注入 localStorage 再跳路由」验证不通，必须走真实表单提交或整页 reload
- **踩坑记录**：PowerShell 管道会把中文变成 `?`，脚本结论要落盘成 UTF-8 JSON 再在 WSL 侧读

---

## Session 2026-09-11
- 旧系统全面梳理完成（Explore agent），产出 findings.md
- 工具链确认: Go/Node/Python/Docker/uv 全可用
- task_plan.md 建立（11 阶段）

### Phase 0: 需求文档 v5.0 — ✅ 完成
- docs/REQUIREMENTS_V5.md 产出（含多Agent圆桌讨论设计、接口契约、修复对照表）
- 已同步覆盖桌面文档 aiagent简历筛选系统设计文档_v4精简版.txt

### Phase 1: Go 基础框架 + 认证 — ✅ 完成
- backend/ 建立：go.mod、config、zerolog 日志、统一响应/错误码、JWT、bcrypt、trace/auth/限流(Redis滑动窗口)/recovery 中间件、GORM+内嵌迁移(7表)、auth service+handler、health liveness/readiness、agentclient
- 修复：zerolog 指针接收者调用（加 logger.L()/LG() 助手）
- `go build ./...` 通过；jwtutil/password 单测通过；go vet 干净
- Docker Desktop 已尝试启动（daemon 初始化中，运行时集成测试顺延）

### Phase 2: Go 业务数据模块 — ✅ 完成
- agenttypes 契约、JobRepo/CandidateRepo/MatchRepo/InteractionRepo/CostRepo/TaskRepo
- JobService（创建即调 agent /parse/jd）、CandidateService（三重文件校验+multipart 转发 /parse/resume）
- handler + 路由挂载（RBAC: hr 读写, manager+ 删）；go build/vet 通过

### Phase 3-4: Python Agent 框架 + 解析向量化 — ✅ 完成
- FastAPI 骨架、X-Internal-Key 鉴权、trace 中间件、错误体系
- LLM 网关：重试(3次指数退避)+熔断(5次/60s)+备用模型+成本计量；无 key 时可启动（调用时报错）
- 解析：pymupdf 文本提取、JD/简历 LLM 抽取、两阶段技能匹配（规则别名→语义降级）、分块嵌入写 Chroma
- 修复：技能匹配改两阶段（语义对英文别名失效）；安全依赖缺 import；LLM 空 key 构造报错

### Phase 5: 混合检索粗筛 — ✅ 完成
- 硬过滤扩展为学历+年限+技能三维；BM25Plus（Okapi 小语料 idf=0 缺陷）；稠密+稀疏→RRF→重排
- 修复：Chroma 不可用时稠密检索优雅降级；候选真实 ID 全链路映射
- tests/test_screening_flow.py：6 个测试全过（mock LLM 全流程事件序列校验）

### Phase 6: 多Agent圆桌讨论 — ✅ 完成
- 5 个 LLM 专家 + 规则型 StabilityAnalyzer（补齐 stability 维度）+ Moderator + 魔鬼代言人
- 仲裁公式经手工验算（置信度×类别权重，73.7 精确吻合）；分歧检测阈值 12；魔鬼代言人不参与加权
- 模型问题解决：hf-mirror 403 → ModelScope 下载 bge-m3(2.27GB)/reranker 到本地 models/
- Chroma 版本对齐：服务端 0.5.5(v1) 与客户端 1.5.9(v2) 不匹配 → 换 1.0.15 服务端
- 开发环境容器：mysql-rec(13306)/redis-rec(6379)/chroma-rec(8001) 全部 Up

### Phase 7: Go 筛选编排与反馈闭环 — ✅ 完成
- ScreeningService：内存队列+worker 池、NDJSON 流消费、Redis Pub/Sub(screen:events:{task_id})、结果/成本/交互日志三路落库
- SSE 端点 /screen/tasks/:id/events（订阅+心跳+done/error 自动断流）、/screen 202 异步受理、match-results 读时个性化加权
- FeedbackService：suitable +0.05 / not_suitable -0.05，clamp ±0.15，Redis 偏好 hash + interaction_log
- 真实端到端验证通过：注册→建岗→传2份PDF简历→筛选任务→圆桌讨论2轮收敛→综合分87.2→反馈→boost 0.05→调分91.56；cost_records 记录 deepseek-chat 3428+1123 tokens/$0.0022

### Phase 8: 面试调度 — ✅ 完成
- Python: /interview/draft（LLM 邮件草稿+PII输出脱敏）、/interview/reply-intent（accept/propose_new_time/decline/other）、/interview/send（MCP email必达+calendar尽力）
- Go: InterviewService 幂等占位 idem:interview:{cid}:{jid} NX+EX 24h（成功保留防重/失败释放可重试）
- 真实验证：草稿生成（含3个时间段）、回复意图（propose_new_time+新时间提取）、mock MCP(9000/9001) 发送成功、重复发送 40901 拒绝

### Phase 9: React TS 前端 — 🔨 约 30%
- 已完成：package.json+依赖安装、vite/tsconfig/index.html、types.ts（含SSE事件）、client.ts（axios+fetch流式SSE）、auth.ts store
- 待完成：main.tsx/App.tsx/5个页面（Login/Jobs/Candidates/Screening/Interview）→ npm run build 验证

---

## 📸 环境快照（恢复会话时参照）

### 开发容器（Docker Desktop）
| 容器 | 镜像 | 宿主端口 | 说明 |
|------|------|---------|------|
| mysql-rec | mysql:8.0 | 13306 | root/password, 库 recruitment（3306被本机其他MySQL占用） |
| redis-rec | redis:7-alpine | 6379 | 无密码 |
| chroma-rec | chromadb/chroma:1.0.15 | 18001 | volume chroma_data（8001留给agent服务） |

### 启动命令（Git Bash, 项目根）
```bash
# 1. agent 服务（:8001）
cd agent && .venv/Scripts/python.exe -m uvicorn app.main:app --port 8001
# 2. backend（:8080）
cd backend && go run ./cmd/server
# 3. 前端 dev（:3000）
cd frontend && npm run dev
# 4. （可选）mock MCP 面试工具（:9000/9001）
agent/.venv/Scripts/python.exe tmp/mock_mcp.py
```

### 配置文件（均已就位，含真实 DeepSeek key）
- agent/.env：LLM_API_KEY=<已脱敏>（真实 key 只存在于本地 .env，已被 .gitignore 排除）、CHROMA_PORT=18001、AGENT_INTERNAL_KEY=dev-internal-key
- backend/.env：DATABASE_URL 指 13306、JWT_SECRET_KEY=dev-jwt-secret-not-for-production、AGENT_BASE_URL=http://localhost:8001
- 本地模型：agent/models/bge-m3（2.27GB）、agent/models/bge-reranker-v2-m3（config 自动优先本地，HF_ENDPOINT=hf-mirror 失效时兜底）

### 已验证测试资产
- 测试账号：hr_admin/password123 @ tenant company_a（role=admin）
- 测试简历：resume_zhang.pdf（Python，张伟）、resume_li.pdf（Java，李娜）、resume_chen.pdf（外包低增长，陈晨，由 tmp/gen_resume.py 生成）— 均在项目根
- tmp/ 下有 jd.json/screen.json/draft.json 等历史载荷可复用；tmp/screen_events.json 是最近一次 SSE 事件全文
- Go 测试：cd backend && go test ./...（jwtutil/password/feedback 调分边界 全过）
- Python 测试：cd agent && .venv/Scripts/python.exe -m pytest tests/ -q（6 个全过，mock LLM 已修正为同步签名）
- 一键端到端：`agent/.venv/Scripts/python.exe tmp/e2e_verify.py`（必须在 Windows 侧跑，见下）
- 前端 dev 验证：`agent/.venv/Scripts/python.exe tmp/frontend_verify.py`（11 个模块转译 + /api 代理 + 登录/列表）

### 关键端口约定
backend 8080 / agent 8001 / chroma 18001 / mysql 13306 / redis 6379 / 前端 3000 / mock MCP 9000-9001

### WSL ↔ Windows 注意事项（本轮踩坑）
- 本机服务跑在 Windows 上（F:\node、F:\Go），**WSL 里 PATH 没有 go/npm/node**；
  Go 用 `/mnt/f/Go/bin/go.exe`，npm 用 `/mnt/f/node/npm.cmd`（直接调 .cmd 会因 CRLF 报 unexpected EOF，
  走 `powershell.exe -Command "Set-Location 'D:\...'; & 'F:\node\npm.cmd' run dev"` 才行）
- **WSL 无法访问 Windows 进程绑在 127.0.0.1 的端口**（只有 0.0.0.0 才可能通），验证脚本一律用
  Windows 版 python 执行；Docker CLI 也只在 Windows 侧（WSL 未开 Docker Desktop 集成）
- WSL 里跑 `npm run build` 需补 `@rollup/rollup-linux-x64-gnu` 与 `@esbuild/linux-x64`（已 --no-save 装好）
- 前端 dev 必须 `npm run dev -- --host 0.0.0.0`，否则只监听 ::1，IPv4 访问被拒

### 当前在跑的服务（2026-09-12 10:50 状态）
| 服务 | 端口 | 启动方式 |
|------|------|---------|
| agent（uvicorn） | 8001 | Windows python（job） |
| backend（go run） | 8080 | /mnt/f/Go/bin/go.exe |
| 前端 vite dev | 3000 | F:\node\npm.cmd run dev -- --host 0.0.0.0 |
| mysql-rec / redis-rec / chroma-rec | 13306 / 6379 / 18001 | Docker Desktop |
- 根目录新增 `.env`（本机 compose 验证用，含真实 key，已加 .gitignore）+ `.gitignore`



