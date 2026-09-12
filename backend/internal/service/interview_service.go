package service

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"

	"github.com/ai-recruitment/backend/internal/agenttypes"
	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/agentclient"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/redisclient"
	"github.com/ai-recruitment/backend/internal/repository"
)

// InterviewService 面试调度编排：草稿(LLM) → 确认 → 幂等发送(MCP) → 回复意图。
type InterviewService struct {
	repos *repository.Repos
	agent *agentclient.Client
	rdb   *redis.Client
}

func NewInterviewService(repos *repository.Repos, agent *agentclient.Client, rdb *redis.Client) *InterviewService {
	return &InterviewService{repos: repos, agent: agent, rdb: rdb}
}

// Draft 生成面试邀请草稿。
func (s *InterviewService) Draft(ctx context.Context, tenantID, jobID, candidateID string, proposedTimes []string) (*agenttypes.InterviewDraft, error) {
	if len(proposedTimes) == 0 || len(proposedTimes) > 10 {
		return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000, "proposed_times 需 1-10 个", 400))
	}
	job, err := s.repos.Job().FindByID(tenantID, jobID)
	if err != nil {
		return nil, err
	}
	cand, err := s.repos.Candidate().FindByID(tenantID, candidateID)
	if err != nil {
		return nil, err
	}
	if cand.Email == "" {
		return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000, "候选人缺少邮箱", 400))
	}
	var out struct {
		Draft agenttypes.InterviewDraft `json:"draft"`
	}
	err = s.agent.PostJSON(ctx, "/interview/draft", map[string]any{
		"job_title":       job.Title,
		"candidate_name":  cand.Name,
		"candidate_email": cand.Email,
		"proposed_times":  proposedTimes,
	}, &out)
	if err != nil {
		return nil, err
	}
	return &out.Draft, nil
}

// Send 幂等发送面试邀请（邮件必达，日历尽力而为）。
func (s *InterviewService) Send(ctx context.Context, tenantID, userID, jobID, candidateID string, draft agenttypes.InterviewDraft, selectedTime string) (map[string]string, error) {
	if _, err := s.repos.Candidate().FindByID(tenantID, candidateID); err != nil {
		return nil, err
	}
	job, err := s.repos.Job().FindByID(tenantID, jobID)
	if err != nil {
		return nil, err
	}

	// 幂等占位：成功后保留 24h 防重复发送；失败即释放以便重试
	guard, err := redisclient.NewIdempotent(ctx, s.rdb, fmt.Sprintf("interview:%s:%s", candidateID, jobID), 24*time.Hour)
	if err == redisclient.ErrLockHeld {
		return nil, apperror.ErrIdempotent
	}
	if err != nil {
		return nil, apperror.New(50002, "幂等检查失败", 502).WithCause(err)
	}

	sent := map[string]string{}
	err = s.agent.PostJSON(ctx, "/interview/send", map[string]any{
		"job_title":       job.Title,
		"candidate_email": draft.CandidateEmail,
		"subject":         draft.Subject,
		"body":            draft.Body,
		"proposed_times":  draft.ProposedTimes,
		"selected_time":   selectedTime,
	}, &sent)
	if err != nil {
		guard.Release(context.WithoutCancel(ctx))
		return nil, err
	}

	_ = s.repos.Interaction().Insert(&model.InteractionLog{
		ID: uuid.NewString(), TenantID: tenantID,
		UserID: userID, EventType: "interview_send", TargetID: candidateID, JobID: jobID,
	})
	return sent, nil
}

// ReplyIntent 候选人回复意图分析。
func (s *InterviewService) ReplyIntent(ctx context.Context, replyBody string) (*agenttypes.ReplyIntent, error) {
	var out struct {
		Intent agenttypes.ReplyIntent `json:"intent"`
	}
	if err := s.agent.PostJSON(ctx, "/interview/reply-intent", map[string]string{"reply_body": replyBody}, &out); err != nil {
		return nil, err
	}
	return &out.Intent, nil
}
