package service

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
	"gorm.io/gorm"

	"github.com/ai-recruitment/backend/internal/agenttypes"
	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/agentclient"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/fingerprint"
	"github.com/ai-recruitment/backend/internal/pkg/logger"
	"github.com/ai-recruitment/backend/internal/pkg/metrics"
	"github.com/ai-recruitment/backend/internal/repository"
)

// ScreeningEvent 筛选事件（NDJSON 行 → Redis Pub/Sub → SSE）。
// Payload 原样透传 agent 事件的业务字段（candidates/agents/result/mean/std/
// needs_discussion/turn/report/results/usage/…），前端按 type 取用。
type ScreeningEvent struct {
	Type       string         `json:"type"`
	TaskID     string         `json:"task_id"`
	Progress   int            `json:"progress,omitempty"`
	Message    string         `json:"message,omitempty"`
	Payload    map[string]any `json:"payload"`
	OccurredAt int64          `json:"occurred_at"`
}

// ScreeningService 异步筛选编排：任务池 → agent NDJSON 流 → Redis Pub/Sub。
type ScreeningService struct {
	repos    *repository.Repos
	agent    *agentclient.Client
	rdb      *redis.Client
	db       *gorm.DB
	timeout   time.Duration
	maxPool   int
	batchSize int

	queue chan *model.ScreeningTask
	wg    sync.WaitGroup

	// checkpoints 任务断点：进程内保存"已完成候选人的精筛报告"（O5）。
	// 任务失败后重试时把它作为幂等缓存喂回 agent，已完成的候选人不再重算。
	// 用 sync.Map + 容量上限：无需跨进程共享，重启后最坏就是整任务重跑。
	checkpoints sync.Map

	ctx    context.Context
	cancel context.CancelFunc
}

func NewScreeningService(repos *repository.Repos, agent *agentclient.Client, rdb *redis.Client, db *gorm.DB,
	timeout time.Duration, queueSize int, batchSize int) *ScreeningService {
	ctx, cancel := context.WithCancel(context.Background())
	return &ScreeningService{
		repos: repos, agent: agent, rdb: rdb, db: db,
		timeout: timeout, maxPool: 200, batchSize: batchSize,
		queue: make(chan *model.ScreeningTask, queueSize),
		ctx:   ctx, cancel: cancel,
	}
}

// Start 启动 worker 池。
func (s *ScreeningService) Start(workers int) {
	for i := 0; i < workers; i++ {
		s.wg.Add(1)
		go s.worker(i)
	}
	logger.LG().Info().Int("workers", workers).Msg("screening workers started")
}

// Stop 优雅停机：停止收新任务，等待在途任务完成。
func (s *ScreeningService) Stop(drainTimeout time.Duration) {
	s.cancel()
	close(s.queue)
	done := make(chan struct{})
	go func() { s.wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(drainTimeout):
		logger.LG().Warn().Msg("screening workers drain timeout")
	}
}


// ---- 任务断点（O5）----

const checkpointTTL = 2 * time.Hour

type taskCheckpoint struct {
	reports  []agenttypes.OverallReport
	updated  time.Time
}

func (s *ScreeningService) saveCheckpoint(taskID string, reports []agenttypes.OverallReport) {
	if len(reports) == 0 {
		return
	}
	cp := make([]agenttypes.OverallReport, len(reports))
	copy(cp, reports)
	s.checkpoints.Store(taskID, taskCheckpoint{reports: cp, updated: time.Now()})
}

func (s *ScreeningService) loadCheckpoint(taskID string) []agenttypes.OverallReport {
	v, ok := s.checkpoints.Load(taskID)
	if !ok {
		return nil
	}
	cp := v.(taskCheckpoint)
	if time.Since(cp.updated) > checkpointTTL {
		s.checkpoints.Delete(taskID)
		return nil
	}
	return cp.reports
}

// RetryTask 失败任务续跑：把上次已完成的候选人报告作为幂等缓存喂给新任务，
// agent 只会对"未完成或简历已变更"的候选人重新精筛。
func (s *ScreeningService) RetryTask(tenantID, userID, taskID string) (*model.ScreeningTask, int, error) {
	prev, err := s.repos.Task().FindByID(tenantID, taskID)
	if err != nil {
		return nil, 0, apperror.ErrTaskNotFound.WithCause(err)
	}
	if prev.Status == model.TaskStatusPending || prev.Status == model.TaskStatusRunning {
		return nil, 0, apperror.New(40902, "任务仍在执行中，无法续跑", 409)
	}
	done := s.loadCheckpoint(taskID)
	task, err := s.Submit(tenantID, userID, prev.JobID, "", prev.CandidatesN)
	if err != nil {
		return nil, 0, err
	}
	if len(done) > 0 {
		// 作为新任务的初始断点：process() 会把它并入 cachedReports
		s.saveCheckpoint(task.ID, done)
	}
	metrics.Inc("screen_retries", 1, nil)
	metrics.Inc("screen_retry_reused_candidates", float64(len(done)), nil)
	logger.LG().Info().Str("task_id", task.ID).Str("parent_task", taskID).
		Int("reused", len(done)).Msg("screening task retried from checkpoint")
	return task, len(done), nil
}

// Submit 受理筛选任务（先落库再入队）。
func (s *ScreeningService) Submit(tenantID, userID, jobID, query string, maxCandidates int) (*model.ScreeningTask, error) {
	if _, err := s.repos.Job().FindByID(tenantID, jobID); err != nil {
		return nil, err
	}
	task := &model.ScreeningTask{
		ID: uuid.NewString(), TenantID: tenantID, JobID: jobID, UserID: userID,
		SessionID: uuid.NewString(), Status: model.TaskStatusPending,
		CandidatesN: maxCandidates,
	}
	if err := s.repos.Task().Create(task); err != nil {
		return nil, err
	}
	select {
	case s.queue <- task:
	default:
		return nil, apperror.New(42901, "筛选任务队列已满，请稍后再试", 429)
	}
	return task, nil
}

func (s *ScreeningService) worker(id int) {
	defer s.wg.Done()
	for task := range s.queue {
		if s.ctx.Err() != nil {
			return
		}
		s.process(s.ctx, task, id)
	}
}

// publish 推送事件到 Redis Pub/Sub（SSE 订阅此通道）。
func (s *ScreeningService) publish(ctx context.Context, taskID string, event ScreeningEvent) {
	event.TaskID = taskID
	event.OccurredAt = time.Now().UnixMilli()
	if data, err := json.Marshal(event); err == nil {
		s.rdb.Publish(ctx, "screen:events:"+taskID, data)
	}
}

func (s *ScreeningService) process(ctx context.Context, task *model.ScreeningTask, workerID int) {
	log := logger.L(ctx).With().Str("task_id", task.ID).Str("worker", fmt.Sprint(workerID)).Logger()
	ctx, cancel := context.WithTimeout(ctx, s.timeout)
	defer cancel()

	task.Status = model.TaskStatusRunning
	_ = s.repos.Task().Update(task)
	taskStarted := time.Now()
	metrics.Inc("screen_tasks_started", 1, nil)
	metrics.SetGauge("screen_tasks_inflight", 1, nil)
	defer metrics.SetGauge("screen_tasks_inflight", 0, nil)
	s.publish(ctx, task.ID, ScreeningEvent{Type: "stage", Progress: 5, Message: "任务开始"})

	// 组装载荷（Python 无状态：数据全部由请求传入）
	job, err := s.repos.Job().FindByID(task.TenantID, task.JobID)
	if err != nil {
		s.failTask(ctx, task, "岗位不存在")
		return
	}
	// 分页加载全量候选人（O4）：此前硬顶 200 人，超出部分被静默丢弃。
	// 现在按页取满，并按页组装成 batches 交给 agent 分批粗筛，内存占用与页大小同阶。
	total, err := s.repos.Candidate().CountByTenant(task.TenantID)
	if err != nil {
		s.failTask(ctx, task, "候选人计数失败")
		return
	}
	if total == 0 {
		s.failTask(ctx, task, "租户内暂无候选人")
		return
	}
	// 批大小优先级：显式配置 SCREEN_BATCH_SIZE > maxPool > 默认页大小
	pageSize := s.batchSize
	if pageSize <= 0 {
		pageSize = s.maxPool
	}
	if pageSize <= 0 {
		pageSize = repository.DefaultScreeningPageSize
	}
	batchPayloads := make([][]map[string]any, 0, int(total)/pageSize+1)
	var candidates []model.Candidate
	for offset := 0; offset < int(total); offset += pageSize {
		page, err := s.repos.Candidate().ListPage(task.TenantID, offset, pageSize)
		if err != nil {
			s.failTask(ctx, task, "候选人加载失败")
			return
		}
		if len(page) == 0 {
			break
		}
		candidates = append(candidates, page...)
		batchPayloads = append(batchPayloads, candidatesPayload(page))
	}
	if len(candidates) == 0 {
		s.failTask(ctx, task, "租户内暂无候选人")
		return
	}
	log.Info().Int("candidates", len(candidates)).Int("batches", len(batchPayloads)).
		Int("batch_size", pageSize).Msg("screening payload assembled")
	if len(batchPayloads) > 1 {
		s.publish(ctx, task.ID, ScreeningEvent{
			Type: "stage", Progress: 4,
			Message: fmt.Sprintf("候选人共 %d 人，分 %d 批粗筛（每批 %d 人）",
				len(candidates), len(batchPayloads), pageSize),
		})
	}

	// 幂等缓存：同一份简历（指纹未变）在同一岗位上已精筛过，就直接复用结论，不再重复调用 LLM。
	// 指纹来自 candidates.profile_hash，缓存来自 match_results.profile_hash。
	cached, err := s.repos.Match().CachedVerdicts(task.TenantID, task.JobID)
	if err != nil {
		log.Warn().Err(err).Msg("load cached verdicts failed, screening without cache")
		cached = map[string]repository.CachedVerdict{}
	}
	// 岗位配置指纹：权重/检索参数/JD 任一变化都必须让缓存失效，
	// 否则会出现"改了岗位配置但分数不变"的错误复用（O7 验证时实测踩到）。
	configHash := fingerprint.JobConfig(job.JDJSON, job.WeightsOverride, job.ScreenOverrides)
	verdicts := make(map[string]repository.CachedVerdict, len(cached))
	for _, c := range candidates {
		v, ok := cached[c.ID]
		if !ok || c.ProfileHash == "" {
			continue
		}
		if v.ProfileHash != c.ProfileHash {
			continue
		}
		if v.ConfigHash != configHash {
			continue // 配置变了 → 必须重算
		}
		verdicts[c.ID] = v
	}
	// 断点续跑（O5）：把上次未完成任务的已完成结论并入幂等缓存（详见 mergeCheckpointVerdicts）
	reusedFromCheckpoint := mergeCheckpointVerdicts(verdicts, s.loadCheckpoint(task.ID))

	missReasons := map[string]int{}
	for _, c := range candidates {
		if _, ok := verdicts[c.ID]; ok {
			continue
		}
		switch {
		case c.ProfileHash == "":
			missReasons["候选人无指纹"]++
		default:
			v, ok := cached[c.ID]
			switch {
			case !ok:
				missReasons["无历史结论"]++
			case v.ProfileHash != c.ProfileHash:
				missReasons["简历已变更"]++
			case v.ConfigHash != configHash:
				missReasons["岗位配置已变更"]++
			}
		}
	}
	stageMsg := fmt.Sprintf("幂等缓存：命中 %d/%d 人（重新精筛 %d 人 %v）",
		len(verdicts), len(candidates), len(candidates)-len(verdicts), missReasons)
	if reusedFromCheckpoint > 0 {
		stageMsg = fmt.Sprintf("断点续跑：复用 %d 人已完成结论（命中 %d/%d 人，重新精筛 %d 人）",
			reusedFromCheckpoint, len(verdicts), len(candidates), len(candidates)-len(verdicts))
	}
	s.publish(ctx, task.ID, ScreeningEvent{Type: "stage", Progress: 8, Message: stageMsg})
	log.Info().Int("cached", len(verdicts)).Int("total", len(candidates)).
		Int("from_checkpoint", reusedFromCheckpoint).
		Interface("miss_reasons", missReasons).Msg("idempotent cache")
	payload := map[string]any{
		"tenant_id": task.TenantID,
		"job": map[string]any{
			"job_id": job.ID, "title": job.Title, "jd_json": job.JDJSON,
			// 岗位级配置（O7）：权重与检索参数覆盖，agent 侧按优先级合并
			"weights_override": job.WeightsOverride,
			"screen_overrides": job.ScreenOverrides,
		},
		"batches":        batchPayloads,
		"pool_size":      len(candidates),
		"cached_reports": verdicts,
		"config": map[string]any{
			"max_candidates": min(task.CandidatesN, 50),
			"query":          "",
			"enable_hyde":    true,
		},
	}

	var reports []agenttypes.OverallReport
	var costs []model.CostRecord
	var failMsg string
	var emptyReason string

	err = s.agent.StreamNDJSON(ctx, "/screening/run", payload, func(line []byte) error {
		// 整行原样解析：agent 各事件字段不同，统一透传给前端
		var raw map[string]any
		if err := json.Unmarshal(line, &raw); err != nil {
			return nil // 忽略无法解析的行，保证流不断
		}
		evType, _ := raw["type"].(string)
		if evType == "" {
			return nil
		}
		// 提取框架字段：type/progress/message 单独承载，其余业务字段进 payload
		evProgress := 0
		if v, ok := raw["progress"].(float64); ok {
			evProgress = int(v)
		}
		evMessage, _ := raw["message"].(string)
		delete(raw, "type")
		delete(raw, "progress")
		delete(raw, "message")

		switch evType {
		case "done":
			// agent 的 done 早于结果落库，不能直接透传，否则前端收到 done 立刻回查会读到 running。
			// 仅在此记录"本轮无结果"的提示，真正的 done 由本服务落库成功后发布。
			if emptyMsg, _ := raw["message"].(string); emptyMsg != "" && evMessage == "" {
				evMessage = emptyMsg
			}
			if n := len(reports); n == 0 {
				emptyReason = evMessage
			}
			return nil
		case "candidate_done":
			var report agenttypes.OverallReport
			if data, err := json.Marshal(raw["report"]); err == nil && json.Unmarshal(data, &report) == nil {
				reports = append(reports, report)
				s.saveCheckpoint(task.ID, reports) // 逐候选落断点：失败后可续跑
			}
		case "cost":
			var u agenttypes.CostUsage
			if data, err := json.Marshal(raw["usage"]); err == nil && json.Unmarshal(data, &u) == nil {
				costs = append(costs, model.CostRecord{
					TenantID: task.TenantID, TraceID: task.ID, ModelName: u.ModelName,
					TokensPrompt: u.TokensPrompt, TokensCompletion: u.TokensCompletion,
					Cost: u.Cost,
				})
			}
		case "error":
			failMsg = fmt.Sprintf("agent error %v: %s", raw["code"], evMessage)
		}
		s.publish(ctx, task.ID, ScreeningEvent{
			Type: evType, Progress: evProgress, Message: evMessage, Payload: raw,
		})
		return nil
	})
	if err != nil {
		s.failTask(ctx, task, "agent 流式调用失败: "+err.Error())
		return
	}
	if failMsg != "" {
		s.failTask(ctx, task, failMsg)
		return
	}

	// 落库：match_results + cost_records + 交互日志
	if err := s.persistResults(ctx, task, job, reports, candidates, configHash); err != nil {
		s.failTask(ctx, task, "结果落库失败: "+err.Error())
		return
	}
	if len(costs) > 0 {
		if err := s.repos.Cost().InsertBatch(costs); err != nil {
			log.Warn().Err(err).Msg("cost records persist failed")
		}
	}
	_ = s.repos.Interaction().Insert(&model.InteractionLog{
		ID: uuid.NewString(), TenantID: task.TenantID, SessionID: task.SessionID,
		UserID: task.UserID, EventType: "screen_end", JobID: task.JobID,
	})

	// 先落库再发 done：前端收到 done 立即回查结果必须已可读（避免读写竞态）
	task.Status = model.TaskStatusSucceeded
	task.Progress = 100
	task.CandidatesN = len(reports)
	if err := s.repos.Task().Update(task); err != nil {
		log.Warn().Err(err).Msg("task status update failed")
	}
	doneMsg := "筛选完成"
	if len(reports) == 0 {
		doneMsg = "筛选完成：无匹配候选人"
		if emptyReason != "" {
			doneMsg = "筛选完成：" + emptyReason
		}
	}
	s.checkpoints.Delete(task.ID)
	metrics.Inc("screen_tasks", 1, map[string]string{"status": "succeeded"})
	metrics.Observe("screen_task_seconds", time.Since(taskStarted).Seconds(), map[string]string{"status": "succeeded"})
	metrics.Inc("screen_candidates_fine", float64(len(reports)), nil)
	metrics.Inc("screen_cache_hits", float64(len(verdicts)), nil)
	metrics.Inc("screen_cache_misses", float64(len(candidates)-len(verdicts)), nil)
	s.publish(ctx, task.ID, ScreeningEvent{Type: "done", Progress: 100, Message: doneMsg})
	log.Info().Int("reports", len(reports)).Msg("screening task succeeded")
}

func (s *ScreeningService) persistResults(ctx context.Context, task *model.ScreeningTask, job *model.Job,
	reports []agenttypes.OverallReport, candidates []model.Candidate, configHash string) error {
	hashByID := make(map[string]string, len(candidates))
	for _, c := range candidates {
		hashByID[c.ID] = c.ProfileHash
	}
	rows := make([]model.MatchResult, 0, len(reports))
	for _, r := range reports {
		dims := model.JSON{}
		for k, v := range r.DimensionScores {
			dims[k] = v
		}
		evidence := model.StringSlice{}
		for _, e := range r.Evidence {
			evidence = append(evidence, e)
		}
		var discussion model.JSON
		if r.Discussion != nil {
			if data, err := json.Marshal(r.Discussion); err == nil {
				_ = json.Unmarshal(data, &discussion)
			}
		}
		if discussion == nil {
			discussion = model.JSON{}
		}
		// Agent 细节（证据+立场轨迹）并入 discussion_json，供审计回放
		agentList := make([]map[string]any, 0, len(r.AgentDetails))
		for _, a := range r.AgentDetails {
			var m map[string]any
			if data, err := json.Marshal(a); err == nil && json.Unmarshal(data, &m) == nil {
				agentList = append(agentList, m)
			}
		}
		discussion["agent_details"] = agentList
		rows = append(rows, model.MatchResult{
			ID: uuid.NewString(), TenantID: task.TenantID, JobID: task.JobID,
			CandidateID: r.CandidateID, TaskID: task.ID,
			OverallScore: r.OverallScore, DimensionScores: dims,
			RecommendationText: r.RecommendationText, Evidence: evidence,
			DiscussionJSON: discussion,
			// 记录本次结果对应的简历指纹 + 岗位配置指纹，下次筛选据此判断能否复用
			ProfileHash: hashByID[r.CandidateID],
			ConfigHash:  configHash,
		})
	}
	if err := s.repos.Match().InsertBatch(rows); err != nil {
		return err
	}
	return nil
}

func (s *ScreeningService) failTask(ctx context.Context, task *model.ScreeningTask, msg string) {
	metrics.Inc("screen_tasks", 1, map[string]string{"status": "failed"})
	task.Status = model.TaskStatusFailed
	task.ErrorMsg = truncate(msg, 500)
	_ = s.repos.Task().Update(task)
	s.publish(ctx, task.ID, ScreeningEvent{Type: "error", Message: truncate(msg, 200)})
	logger.L(ctx).Error().Str("task_id", task.ID).Str("reason", msg).Msg("screening task failed")
}

func candidatesPayload(candidates []model.Candidate) []map[string]any {
	out := make([]map[string]any, 0, len(candidates))
	for _, c := range candidates {
		structured := map[string]any(c.StructuredJSON)
		if structured == nil {
			structured = map[string]any{}
		}
		out = append(out, map[string]any{
			"candidate_id":    c.ID,
			"resume_text":     c.ResumeText,
			"structured_json": structured,
		})
	}
	return out
}

func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// mergeCheckpointVerdicts 把断点报告合并进幂等缓存，返回新增条数。
// 语义（O5）：
//   - 断点条目 ProfileHash 置空，表示"该结论来自本任务的父任务断点"，允许直接命中；
//   - 若该候选人已在 DB 缓存里（本轮简历未变），保留 DB 缓存（含指纹），不覆盖；
//   - 只对未完成的候选人补结论，已完成者不会被重算。
func mergeCheckpointVerdicts(verdicts map[string]repository.CachedVerdict, reports []agenttypes.OverallReport) int {
	added := 0
	for _, r := range reports {
		if _, exists := verdicts[r.CandidateID]; exists {
			continue
		}
		dims := map[string]interface{}{}
		for k, v := range r.DimensionScores {
			dims[k] = v
		}
		disc := map[string]interface{}{}
		if r.Discussion != nil {
			if data, err := json.Marshal(r.Discussion); err == nil {
				_ = json.Unmarshal(data, &disc)
			}
		}
		agentList := make([]map[string]any, 0, len(r.AgentDetails))
		for _, a := range r.AgentDetails {
			var m map[string]any
			if data, err := json.Marshal(a); err == nil && json.Unmarshal(data, &m) == nil {
				agentList = append(agentList, m)
			}
		}
		disc["agent_details"] = agentList
		verdicts[r.CandidateID] = repository.CachedVerdict{
			OverallScore:       r.OverallScore,
			DimensionScores:    dims,
			RecommendationText: r.RecommendationText,
			Evidence:           r.Evidence,
			Discussion:         disc,
			ProfileHash:        "", // 空指纹 = 来自断点，匹配逻辑允许命中
		}
		added++
	}
	return added
}
