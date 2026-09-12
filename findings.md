# 发现与关键事实（旧系统梳理，重构依据）

## 旧系统能力清单（必须保留）
1. **JD解析**: LLM 抽取 title/hard_requirements/soft_requirements/skill_graph/job_category(tech|management|design|general)
2. **简历解析**: pymupdf 提文本(>50字符) → PaddleOCR 后备 → LLM 结构化 CandidateProfile(name/email/phone/work_experience/education/skills) → PII 脱敏(身份证) → 技能标准化(语义匹配>0.7归一到18个标准标签,规则后备) → (tenant,email) upsert → 分块(500/重叠50)嵌入写 Chroma "resumes"
3. **混合粗筛**: 硬性过滤(仅学历JSON_CONTAINS) → HyDE改写 → 稠密(Chroma where tenant_id, top30, score=1-dist) → BM25(k1=1.5,b=0.75) → RRF(k=60) → BGE-Reranker(阈值0.4) → top10
4. **多Agent精筛**: 按岗位类别选Agent组 — TECH:Interviewer+Skill+CultureFit / MANAGEMENT:Interviewer+Leadership+CultureFit / DESIGN:Interviewer+Skill+Visual(MCP视觉检索,失败回退LLM) / GENERAL:Interviewer+CultureFit。每Agent输出 {score 0-100, dimension_scores, evidence[], confidence 0-1}
5. **辩论仲裁**: stdev>15 或 agent≤1 时最多2轮，最低分vs最高分互相反驳，最终 calculate_weighted_score（**实为简单平均，公式未接线**）
6. **可解释报告**: OverallReport{candidate_id, overall_score, dimension_scores, recommendation_text(LLM 50字), evidence去重, agent_details}
7. **反馈闭环**: suitable→+0.1 / not_suitable→-0.1 写 Redis user:{id}:prefs；apply_personalized_boost: score*(1+boost)
8. **面试调度**: LLM生成邀请邮件草稿 → 幂等锁(idem:interview:{cid}:{jid}, NX EX 86400) → MCP email(localhost:9000)/calendar(localhost:9001) → 回复意图分析(accept|propose_new_time|decline)
9. **记忆**: interaction_log(MySQL) + 交互摘要嵌入写 Chroma "interaction_summaries" + SessionMemory(Redis session:{id}, TTL 24h) + 高潜候选人查询
10. **非功能**: 多租户 tenant_id contextvar 贯穿所有 SQL；JWT HS256 60min；bcrypt；slowapi 限流(login 10/min, upload 20/min, screen 5/min)；Redis Lua 原子锁；熔断(pybreaker 5次/60s)+重试(tenacity 3次指数退避)；trace_id 中间件；PII 正则(phone/email/id_card)

## 关键常量
DEFAULT_RAG_TOP_K=30, RERANK_THRESHOLD=0.4, DEBATE_STD_THRESHOLD=15.0, DEBATE_MAX_ROUNDS=2, RRF_K=60, CHUNK_SIZE=500, OVERLAP=50, SESSION_TTL=24h, WEIGHTS_TECH={skill:.35, experience:.35, culture:.15, stability:.15}

## 旧系统缺口（重构必须修复）
1. BM25/Chroma 结果未映射真实 candidate_id（"bm25_{i}"/"unknown" 占位）
2. calculate_weighted_score 实为平均分，0.35/0.35/0.15/0.15 公式未接线
3. hard_filter 仅实现学历维度
4. graph.py fine_screening 同时有条件边+无条件边（歧义）
5. CostRepository/langfuse/parse_resume_task/job_summarizer 无调用方（断链）
6. RBAC require_role 已写但未挂任何路由
7. 限流用内存 storage（多副本失效）
8. rough_screening.py 与 hybrid_screener.py 大面积重复
9. checkpoint 用进程内 MemorySaver
10. schedule 节点/handle_reply 半桩实现

## 环境事实
- 工具链: Go 1.27.1 / Node 24.18 / Python 3.13 / Docker 29 / uv 0.11.10（Windows + Git Bash）
- pip 用华为云镜像；Go 需 GOPROXY=https://goproxy.cn（国内网络）
- LLM: DeepSeek (LITELLM_MODEL=deepseek-chat, base https://api.deepseek.com/v1)；DEEPSEEK_API_KEY 从 .env 读
- 嵌入: BGE-M3 (BAAI/bge-m3, 1024维, HF_ENDPOINT=hf-mirror.com)，后备 all-MiniLM-L6-v2；重排 BGE-Reranker-v2-m3
- 旧 MySQL 库名 recruitment，6表: users/jobs/candidates/match_results/interaction_log/cost_records，id 均 CHAR(36)
- Chroma collections: resumes(1024维) / interaction_summaries / job_summaries(无写入方)

## 新架构关键决策（详见 docs/REQUIREMENTS_V5.md）
- Go 独占 MySQL；Python 无状态（JD文本+候选数据由请求传入，只写 Chroma）
- 筛选 NDJSON 流式事件 → Go worker 转 Redis Pub/Sub → SSE → 前端实时讨论视图
- 圆桌讨论: 独立评估→分歧检测(加权均值+std,阈值12)→圆桌≤2轮(只传摘要省token)→魔鬼代言人(全体≥80时注入)→仲裁(真实加权公式+置信度)

## 端到端实测结论（2026-09-12，真实 DeepSeek + BGE-M3 本地模型）
1. **JD解析**：中文 JD → tech 类别、6条硬性要求、技能图谱全对（1次LLM调用）
2. **简历解析**：中文 PDF → 姓名/邮箱/经历/技能正确；技能标准化两阶段生效（FastAPI→Python 保留、机器学习→Machine Learning）
3. **混合粗筛**：2份简历入 Chroma（1024维BGE-M3），Python候选人在无FastAPI技能词时依然入池（硬过滤只卡学历——按设计）
4. **圆桌讨论**：3 LLM专家+StabilityAnalyzer，std=13.3>12 触发2轮讨论，全部 maintain（各自论证充分），convergence=converged；张伟综合87.2（interviewer92×0.35 + skill88×0.35 + culture62×0.15 + stability90×0.15 按置信度加权≈87.2 吻合）
5. **成本计量**：3428+1123 tokens / $0.0022 自动落 cost_records（v4 断链已修复）
6. **反馈闭环**：suitable→boost0.05→87.2×1.05=91.56 读时调分生效
7. **面试调度**：草稿(3时间段)+回复意图(propose_new_time 提取"周五上午10点")+MCP发送+幂等409 全链路验证
8. **讨论质量观察**：culture_fit 给62分且维持原判时，interviewer/skill_evaluator 主动论证"文化分不构成否决项"——多Agent间证据交换真实发生

## 坑与解法（新增，恢复会话时优先看）
- Git Bash 终端 curl 直接写中文 → GBK 乱码进后端：中文载荷必须写 tmp/*.json 文件再 `--data-binary @file`
- Windows 下后台进程用 `(cmd &)` 启动的 uvicorn 不会被 `taskkill //IM python.exe` 全杀，需按 PID：`netstat -ano | grep :8001` 找 PID 再 `taskkill //F //PID x`
- chroma Http客户端构造即发请求（get_user_identity），连接失败会在 import/构造期抛错——hybrid_screener._dense_retrieval 已包 try 降级为空列表
- agent/.env 的 env_file 相对路径：pydantic-settings 是相对 CWD 解析的，用 `os.path.abspath(__file__)` 上三级才稳
- LLMClient 构造不能因缺 key 失败（OpenAI(api_key=...) 要非空串），否则健康检查都会挂——给 "sk-empty" 占位，chat() 时再校验

## SSE 事件契约（v5 最终形态，改动前必读）
- **协议层**：agent `/screening/run` 输出 NDJSON（一行一事件）→ Go `StreamNDJSON` 逐行解析 →
  Redis Pub/Sub `screen:events:{task_id}` → SSE `data: {json}\n\n`（15s 心跳注释行）
- **事件信封**：`{type, task_id, progress?, message?, payload:{...}, occurred_at}`
  - `payload` 原样透传 agent 业务字段（Go 端整行解析后只摘出 type/progress/message）
- **各事件 payload 字段**（实测核对）：
  | type | payload |
  |------|---------|
  | stage | stage, (progress) |
  | rough_result | candidates[{candidate_id,score,rrf_score,evidence,reasons}], pool_size |
  | fine_start | candidate_id, agents[] |
  | agent_result | candidate_id, result{agent,score,dimension_scores,evidence,confidence,stance,reasoning,round} |
  | divergence | candidate_id, mean, std, needs_discussion |
  | discussion | candidate_id, turn{round,agent,stance,content,score,score_delta} |
  | candidate_done | candidate_id, report{overall_score,dimension_scores,recommendation_text,evidence,agent_details,discussion{turns,meta}} |
  | cost | usage{model_name,tokens_prompt,tokens_completion,cost} |
  | candidate_failed | candidate_id, (message) |
  | fine_done | （空） |
  | error | code, (message) |
  | done | （空；message 由 backend 填） |
- **done 只能由 backend 发**：agent 的 done 早于结果落库，若直接透传，前端收到 done 立刻 `GET /screen/tasks/{id}`
  会读到 status=running / results 为空（已复现并修复）。backend 现在是「persistResults → 任务置 succeeded → publish done」
- **前端消费方式**：fetch + ReadableStream（EventSource 不能带 Authorization），
  `normalizeEvent()` 把 payload 平铺一层，代码里直接读 `ev.payload.xxx`
- **结果区 Task 归属**：`match-results` 返回岗位全量历史结果（按 candidate 每任务一行，重复筛同一候选人会有多行），
  前端按 `task_id === 当前任务` 过滤展示，避免历史分混排

## 前端与部署关键事实（2026-09-12 验证）
- `frontend`：React18 + Vite5 + AntD5 + zustand + axios；HashRouter（免 nginx history 配置）；
  `npm run build` = `tsc -b && vite build`，类型零错误；产物单 chunk 1.28MB（gzip 405KB）
- Windows 侧 npm 在 `F:\node`，Go 在 `F:\Go`（WSL 里 PATH 没有，需用 `/mnt/f/Go/bin/go.exe`）；项目在 D 盘
- WSL 访问 Windows 进程的 loopback：**只有绑 0.0.0.0 的端口才通**（8001/8080 绑 0.0.0.0 时 `curl 127.0.0.1` 仍可能拒，
  可靠做法是用 Windows 版 python 跑验证脚本）
- WSL 里跑 `vite build` 需补 Linux 原生包：`npm i --no-save @rollup/rollup-linux-x64-gnu @esbuild/linux-x64`
  （Windows 上 npm install 不会装它们）
- nginx 反代 `/api/` 必须 `proxy_pass http://backend:8080/;`（**带尾斜杠**），否则前缀被替换掉，接口全 404
- Chroma 探活：服务端 1.0.15 暴露 `/api/v2/heartbeat`（客户端 1.5.9 默认 v2）
- compose 校验命令（WSL 无 docker，走 Windows CLI）：
  `powershell -Command "& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose --env-file .env -f deploy/docker-compose.yml config --quiet"`

## 测试资产与验证脚本（本轮新增）
- `tmp/e2e_verify.py`：Windows 侧 python 一键端到端（登录→建岗→传 3 份简历→筛选+SSE 事件透传断言→
  任务状态→反馈调分→面试草稿→回复意图），事件原文落盘 `tmp/screen_events.json`
- `tmp/gen_resume.py`：PyMuPDF 造中文简历 PDF（`resume_chen.pdf`，外包低增长画像，用于测硬过滤/分歧）
- `tmp/agent_probe.py`：直连 agent `/screening/run` 排查 NDJSON 原始事件
- 强制触发圆桌讨论：`DEBATE_STD_THRESHOLD=2` 环境变量重启 agent（默认 12；实测强制触发后 2 轮 6 发言、converged）
- Go 单测：`cd backend && go test ./...`（jwtutil/password/feedback ApplyBoost 调分边界）

## 本机 Docker 构建限制（2026-09-12 实测，未跑完项）- `deploy/docker-compose.yml`：`docker compose config --quiet` **校验通过**
- 镜像：`ai-recruitment/frontend:latest`（75.3MB）**构建成功**（node:22-alpine / nginx:1.27-alpine 当时在本地缓存）
- `backend` / `agent` 镜像构建**未跑完**：基础镜像 `golang:1.24-alpine`、`python:3.13-slim` 本地无缓存，
  而远端仓库被限流 —— `docker manifest inspect` 对 `docker.xuanyuan.me` 返回 `toomanyrequests: 免费节点当前繁忙`；
  `docker.1ms.run`/`registry-1.docker.io` 失败；`docker.m.daocloud.io` 与 `hub.rat.dev` 的 `/v2/` 可达（401 属正常）
  但实际 pull 卡住 6 分钟以上无进展。BuildKit 层面表现为 `docker system df` 的 Build Cache 停在同一尺寸、
  `com.docker.build` 进程 CPU 不增长（= 在等网络，不是编译问题）
- 结论：这是**镜像仓库网络问题，不是 Dockerfile/编排问题**；换可用源拉取基础镜像并 retag 后即可构建（步骤见 deploy/RUNBOOK.md 第 2 节）



## 登录演示（本地）可用性结论（2026-09-12 实测）
- **可用**：三服务在跑时，浏览器打开 http://localhost:3000 → 自动跳 `/#/login` → 填租户/用户名/密码 →
  点「登 录」→ 进入 `/#/screening`（侧边 4 项菜单 + 租户与角色显示正确）。注册 Tab 同理，注册即登录直达主页。
- 演示账号（已存在）：`demo_show` / `hr_76f8` / `demo-password-123`（admin）；
  老账号：`company_a` / `hr_admin` / `password123`（admin）
- 演示前置：`mysql-rec`(13306)、`redis-rec`(6379)、`chroma-rec`(18001) 容器 + agent(8001) + backend(8080) + 前端(3000)
- 登录页契约：POST /api/v1/auth/login {username,password,tenant_id} → data{access_token,token_type,user_id,tenant_id,role}
  ；注册同结构（本轮修复）；前端登录态存 localStorage key = `ai-recruit-auth`
- 注册/登录实测（真实浏览器 CDP 交互）：注册新租户 → 直达 /#/screening；登录 → 直达 /#/screening
- 演示时的两个注意点：
  1) 演示新租户时候选人库为空，筛选页会提示「请先到候选人页上传简历」（预期行为）
  2) 面试「确认发送」依赖 mock MCP（9000/9001）：本机已在跑，实测 `status=sent`
     （email_id=email_5 / calendar_event_id=event_4，见 tmp/interview_send_check.py）；
     换机器演示前需先启动 `tmp/mock_mcp.py`
- 演示租户 `demo_show` 现状：1 岗位（Python 后端工程师 AI 平台）+ 2 候选人（张伟/陈晨）+ 已完成筛选任务与匹配结果

## 环境稳定性坑（2026-09-12 晚，实际踩到）
- **Docker Desktop 一重启，本机开发依赖全停**：`mysql-rec`(13306) / `redis-rec`(6379) / `chroma-rec`(18001)
  最初是 `docker run` 起的、restart policy = no → 容器不会自动恢复，
  表现为「前端能打开、接口在，但登录/注册等一切数据库操作失败」（backend 连接池报 connection refused）
- 恢复命令：
  ```bash
  docker start mysql-rec redis-rec chroma-rec      # 容器还在（数据卷未丢），直接 start 即可
  docker update --restart unless-stopped mysql-rec redis-rec chroma-rec   # 防止下次再犯
  agent/.venv/Scripts/python.exe tmp/dev_stack.py status   # 一键检查（含端口就绪等待）
  ```
- 数据安全：mysql/redis 用的是**匿名卷**（随容器生命周期保留），chroma 用命名卷 `chroma_data`；
  只要容器对象还在，`docker start` 就能恢复全部数据（已实测：岗位 1 + 候选人 2 一条没丢）
- 日志特征：backend `tmp/backend-run.log` 会刷 `[mysql] ... connection refused` 或 `readyz` 里 `mysql: fail`

## 评审发现的缺陷与已修项（2026-09-12 晚）
- ✅ 已修：**技能子串误判**——`Java` 命中 `JavaScript`、`C` 命中 `CSS`（实测复现），
  现走 `skill_hit()` 词边界匹配（英文技能），中文技能仍子串匹配；硬过滤与粗筛理由共用该函数
- ✅ 已修：**年限硬编码 2026** → `datetime.date.today().year`
- ⚠️ 未修（已知设计限制，按优先级排）：
  1. `LoadForScreening` 上限 200 人，大批量岗位需要「分页粗筛 + 游标」而不是一次全量加载
  2. 同一候选人重复筛选会重复精筛（无缓存/幂等），LLM 成本随重复触发线性增长
  3. `interaction_log` 的 summary_vector_id 字段与 Chroma `interaction_summaries` 集合未接线（旧系统有）
  4. 无 Prometheus/OpenTelemetry 指标，只有 zerolog 日志 + 零散 /healthz
  5. 缺失业务能力：已淘汰候选人归档（黑名单）、地点/薪资/到岗时间等硬条件、ATS 对接、
     多轮面试与 offer 流程、筛选结果导出/分享
  6. 智能筛选失败无断点续跑：单候选失败会中断整任务（已改为逐候选 try，但任务级重试需人工重跑）
  7. 偏好学习是全局 ±0.05/次（clamp ±0.15），未按技能/岗位维度学习，也未纳入 rerank

## O1 优化中发现的坑（2026-09-12，已修）
- **FlagEmbedding 推理非线程安全**：`encode()` / `compute_score()` 共享 tokenizer 与内部缓冲，
  并发调用（后台向量化 ∥ 精筛重排）会抛
  `AttributeError: 'list' object has no attribute 'keys'`（`tokenizer.pad()` 收到 list），
  表现为筛选任务整体超时失败。修复：`embedding_client` 内加两把**独立**推理锁 + 针对该签名的定向重试。
  教训：给「懒加载单例 + 重模型」加并发路径时，必须同时加推理锁，不能只锁加载。
- **懒加载模型的冷启动会计入首个请求**：BGE-M3 实测加载 28.9s、reranker 9.9s。
  串行 warmup 会让首个请求等两者之和（~38s），必须并行 warmup；
  且 `/healthz` 要有 `checks.embedder` 才能区分「服务活着」与「模型未就绪」。
- **嵌入成本与 chunk 长度强相关**：BGE-M3 默认 `max_length=8192`，而简历 chunk 只有 500 字符，
  显式 `max_length=512` 避免大量 padding 的无谓计算。
- **重复嵌入容易漏**：技能标准化此前每次上传都重新嵌入 18 个**常量**标准标签，
  改成进程内缓存；一句话——凡是对常量集合做嵌入，都该缓存。

## O3 优化中的坑（2026-09-12，已修）
- **显式白名单的 Upsert 更新分支会漏字段**：`r.db.Model(&existing).Updates(map[string]interface{}{...})`
  只更新 map 里列出的列。给表加了 `profile_hash` 后忘记同步加进这个 map，
  导致「重新上传简历」指纹始终为空、幂等缓存永远不命中（排查花了 3 轮，因为接口返回 201 一切正常）。
  → 教训：这类写法必须在代码里留注释，或改用 `Select("*").Updates(c)` 配合零值处理。
- **诊断代码本身会崩**：`c.ProfileHash[:8]` 在空串上 panic，直接把 backend 打挂（筛选任务报连接重置）。
  日志截断一律用安全函数，别直接在结构体字段上切片。
- **缓存命中统计口径**：backend 只在粗筛阶段给出 `cache_hits`，agent 再为每个命中候选补
  `candidate_done{cached:true}`，两处都累加会翻倍（验证脚本踩过）。

## O4 优化要点（2026-09-12）
- **静默截断是最危险的缺陷类型**：`limit>200 → 200` 不报错、日志也不提示，只是"人少了"。
  凡是上限，要么显式报错、要么分页取满，不能悄悄丢数据。
- **分页排序必须稳定**：`ORDER BY created_at DESC, id ASC`——只按时间排序时同一秒创建的多行顺序不定，翻页会漏。
- **分批后重排要收敛**：逐批重排会让跨批候选人分数不可比（各批候选面不同），必须合并后再统一重排一次。
- 查询侧成本要跨批复用：HyDE 改写（LLM）与查询向量（嵌入）各只算一次，否则批数越多成本线性上涨。
- Go 集成测试要自己找 .env：`go test` 的工作目录在包内，`config.Load()` 只找 CWD，向上遍历注入环境变量即可
  （库不可达时 `t.Skip` 保证 CI 无外部依赖也能过）。

## WSL→Windows 环境变量陷阱（2026-09-12 实测，排查耗时较长，务必先看这条）
在 WSL 里给 **Windows 可执行文件**（`go run` 编译产物、`go.exe`、`node.exe`）传临时环境变量是不可靠的：
- `bash -c 'VAR=1 cmd'` 对 WSL 原生程序有效（已验证子进程能看到），但 **Windows 程序常常收不到**；
- 实测：`SCREEN_TASK_TIMEOUT_SEC=3 ./dsh-backend.exe` → 启动日志显示 `timeout_sec=300`（默认值）；
  经 PowerShell 再启动同样拿不到；而 PowerShell 自己的 `$env:VAR` 能设置成功。
- **可靠做法**：把配置写进程序自己会读的配置文件（本项目是 `backend/.env` / `agent/.env`），
  或在 **PowerShell 里先 `$env:VAR='x'` 再启动**并当场用启动日志确认生效。
- 教训：验证脚本必须在启动日志里**打印关键配置的解析结果**（本轮就是靠 `screening config batch_size=...`
  才确认环境变量没传进去，否则会误判成功能 bug 去改业务代码）。

## 已修真实缺陷（O5 验证过程中发现）
- ✅ **`SCREEN_BATCH_SIZE` 配了不生效**：`process()` 里 `pageSize := s.maxPool` 覆盖了新加的
  `s.batchSize` 优先级判断（源于早先一次字符串替换静默失败）。
  现象很有迷惑性：启动日志 `screening config batch_size=1`，任务日志却是 `batch_size=200`，
  看起来像"同一进程读同一配置得到两个值"。**教训：改配置读取逻辑后，必须在任务侧日志复核实际生效值。**
- ✅ **任务超时对 NDJSON 流无效**：agent 客户端的 HTTP 超时是 90s 固定值，任务超时到点只取消 context，
  流不会被切断 → 任务照跑到底。已改为 `agentHTTPTimeout = 任务超时 + 30s`。
- 结论：**凡"超时/限额类配置"，都要在真实链路里验证它真的会中断**，不能只看代码里有这行。

## O6 指标实现踩坑（2026-09-12，已修）
- **直方图"存什么"必须先定死**：同一份代码里先后犯过两种错——
  Go 侧存区间计数却按累积渲染（bucket 值可以大于 count）、Python 侧存累积值又在渲染时累积（bucket 非单调）。
  正确定义：存储区间计数，渲染时累积；不变式是 `bucket 单调不减` 且 `+Inf == _count`。
  现在两端各有测试钉死（`metrics_test.go` / `test_metrics.py`）。
- **Prometheus 命名规范**：`_total` 是计数器专用后缀，名字已带 `_total` 不能渲染成 `_total_total`；
  `le` 是普通标签，必须带引号（Python 侧曾输出 `le=0.5`，Go 侧为 `le="0.5"`，抓取端解析规则不一致）。
- **瞬时值用 gauge 不用 counter**：`screen_tasks_inflight` 早期用计数器（渲染成 `_in_flight_total`），
  语义错误，已改 SetGauge。
- 验证脚本自己也错过一次：解析 bucket 时正则只匹配空标签行，把不同 route/stage 的行混在一起比较，
  误报"bucket 非单调"。**指标断言必须按完整标签键分组**。

## O7 踩坑（2026-09-12，已修）
- **缓存键要覆盖"影响结果的全部输入"**：幂等缓存最初只按简历指纹命中，
  改岗位权重后重筛仍复用旧结论 → 表现成"配置改了但分数不变"。
  正确做法：`config_hash = f(JD, 权重, 检索参数)`，命中需同时满足简历指纹与配置指纹。
  推广：任何"结果缓存"都要问一句"还有哪些输入会影响结果"。
- **GORM `Updates(map)` 的值必须能被 driver 处理**：直接放 `map[string]float64` 报
  `unsupported type map[string]interface {}, a map`；要转成实现了 `driver.Valuer` 的类型（本项目 `model.JSON`）。
- **配置读取要单一入口**：粗筛参数曾出现"岗位覆盖用 `_cfg()`、模式判断用会话级函数"的不一致，
  差点造成"按 cosine 算分、按 cross-encoder 取阈值"。现在模式解析统一为
  岗位覆盖 > 会话覆盖 > 全局，并有测试钉死。
- **并发任务不要用全局变量传会话配置**：用 `contextvars`（`apply_overrides`/`reset_overrides`），
  否则多岗位并发筛选会互相串味。
