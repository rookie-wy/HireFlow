package handler

import (
	"encoding/json"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"

	"github.com/ai-recruitment/backend/internal/middleware"
	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/response"
	"github.com/ai-recruitment/backend/internal/repository"
	"github.com/ai-recruitment/backend/internal/service"
)

// ScreenHandler 筛选任务接口。
type ScreenHandler struct {
	screening *service.ScreeningService
	feedback  *service.FeedbackService
	repos     *repository.Repos
	rdb       *redis.Client
}

func NewScreenHandler(ss *service.ScreeningService, fb *service.FeedbackService, repos *repository.Repos, rdb *redis.Client) *ScreenHandler {
	return &ScreenHandler{screening: ss, feedback: fb, repos: repos, rdb: rdb}
}

type ScreenRequest struct {
	JobID         string `json:"job_id" binding:"required"`
	Query         string `json:"query"`
	MaxCandidates int    `json:"max_candidates" binding:"min=1,max=50"`
	SessionID     string `json:"session_id"`
}

// Submit 发起筛选（异步 202）。
func (h *ScreenHandler) Submit(c *gin.Context) {
	var req ScreenRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Fail(c, err)
		return
	}
	if req.MaxCandidates == 0 {
		req.MaxCandidates = 10
	}
	task, err := h.screening.Submit(middleware.TenantID(c), middleware.UserID(c), req.JobID, req.Query, req.MaxCandidates)
	if err != nil {
		response.Fail(c, err)
		return
	}
	// 记录筛选开始事件
	_ = h.repos.Interaction().Insert(&model.InteractionLog{
		TenantID: middleware.TenantID(c), SessionID: task.SessionID,
		UserID: middleware.UserID(c), EventType: "screen_start", JobID: req.JobID,
	})
	response.Accepted(c, gin.H{"task_id": task.ID, "status": task.Status, "session_id": task.SessionID})
}

// TaskStatus 任务状态 + 已产出的匹配结果（读时个性化加权）。
func (h *ScreenHandler) TaskStatus(c *gin.Context) {
	tenantID := middleware.TenantID(c)
	task, err := h.repos.Task().FindByID(tenantID, c.Param("task_id"))
	if err != nil {
		response.Fail(c, apperror.ErrTaskNotFound.WithCause(err))
		return
	}
	boost := h.feedback.PersonalizedBoost(c.Request.Context(), middleware.UserID(c))
	results, _ := h.repos.Match().ListByJob(tenantID, task.JobID)
	type BoostedResult struct {
		model.MatchResult
		AdjustedScore float64 `json:"adjusted_score"`
	}
	out := make([]BoostedResult, 0, len(results))
	for _, r := range results {
		out = append(out, BoostedResult{MatchResult: r, AdjustedScore: h.feedback.ApplyBoost(r.OverallScore, boost)})
	}
	response.OK(c, gin.H{"task": task, "boost": boost, "results": out})
}

// MatchResults 岗位全量匹配结果（含讨论记录，读时个性化加权）。
func (h *ScreenHandler) MatchResults(c *gin.Context) {
	tenantID := middleware.TenantID(c)
	jobID := c.Query("job_id")
	if jobID == "" {
		response.Fail(c, apperror.ErrBadRequest.WithCause(apperror.New(40000, "job_id 必填", 400)))
		return
	}
	results, err := h.repos.Match().ListByJob(tenantID, jobID)
	if err != nil {
		response.Fail(c, err)
		return
	}
	boost := h.feedback.PersonalizedBoost(c.Request.Context(), middleware.UserID(c))
	type BoostedResult struct {
		model.MatchResult
		AdjustedScore float64 `json:"adjusted_score"`
	}
	out := make([]BoostedResult, 0, len(results))
	for _, r := range results {
		out = append(out, BoostedResult{MatchResult: r, AdjustedScore: h.feedback.ApplyBoost(r.OverallScore, boost)})
	}
	response.OK(c, gin.H{"boost": boost, "results": out})
}

// Retry 失败任务续跑：复用已完成的候选人结论，只补未完成部分。
func (h *ScreenHandler) Retry(c *gin.Context) {
	taskID := c.Param("task_id")
	task, reused, err := h.screening.RetryTask(middleware.TenantID(c), middleware.UserID(c), taskID)
	if err != nil {
		response.Fail(c, err)
		return
	}
	_ = h.repos.Interaction().Insert(&model.InteractionLog{
		TenantID: middleware.TenantID(c), SessionID: task.SessionID,
		UserID: middleware.UserID(c), EventType: "screen_retry", JobID: task.JobID,
	})
	response.Accepted(c, gin.H{
		"task_id": task.ID, "status": task.Status, "session_id": task.SessionID,
		"parent_task_id": taskID, "reused_candidates": reused,
	})
}

// Events SSE 实时事件流（订阅 Redis Pub/Sub，done/error 自动结束）。
func (h *ScreenHandler) Events(c *gin.Context) {
	taskID := c.Param("task_id")
	tenantID := middleware.TenantID(c)

	if _, err := h.repos.Task().FindByID(tenantID, taskID); err != nil {
		response.Fail(c, apperror.ErrTaskNotFound.WithCause(err))
		return
	}
	if h.rdb == nil {
		response.Fail(c, apperror.New(50002, "Redis 不可用，无法订阅事件", 502))
		return
	}

	ctx := c.Request.Context()
	sub := h.rdb.Subscribe(ctx, "screen:events:"+taskID)
	defer sub.Close()

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	flusher, canFlush := c.Writer.(httpFlusher)
	clientGone := c.Request.Context().Done()
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-clientGone:
			return
		case <-ticker.C:
			if _, err := c.Writer.WriteString(": heartbeat\n\n"); err != nil {
				return
			}
			if canFlush {
				flusher.Flush()
			}
		case msg, ok := <-sub.Channel():
			if !ok {
				return
			}
			payload := msg.Payload
			if !json.Valid([]byte(payload)) {
				continue
			}
			if _, err := c.Writer.WriteString("data: " + payload + "\n\n"); err != nil {
				return
			}
			if canFlush {
				flusher.Flush()
			}
			var ev struct {
				Type string `json:"type"`
			}
			if json.Unmarshal([]byte(payload), &ev) == nil && (ev.Type == "done" || ev.Type == "error") {
				return
			}
		}
	}
}

type httpFlusher interface{ Flush() }
