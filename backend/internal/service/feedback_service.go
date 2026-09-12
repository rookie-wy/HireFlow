package service

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"

	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/repository"
)

// FeedbackService 反馈闭环：交互日志 + 个性化偏好。
type FeedbackService struct {
	repos *repository.Repos
	rdb   *redis.Client
}

func NewFeedbackService(repos *repository.Repos, rdb *redis.Client) *FeedbackService {
	return &FeedbackService{repos: repos, rdb: rdb}
}

const (
	FeedbackSuitable    = "suitable"
	FeedbackNotSuitable = "not_suitable"
	FeedbackPending     = "pending"

	prefsKeyFmt = "user:%s:prefs"
	// 每条反馈对个性化系数的增量（suitable +delta / not_suitable -delta）
	prefDelta   = 0.05
	boostClamp  = 0.15
)

var validFeedback = map[string]bool{FeedbackSuitable: true, FeedbackNotSuitable: true, FeedbackPending: true}

// Process 记录反馈并更新用户偏好（Redis hash: suitable/not_suitable 计数）。
func (s *FeedbackService) Process(ctx context.Context, tenantID, userID, candidateID, jobID, feedback, sessionID string) error {
	if !validFeedback[feedback] {
		return apperror.ErrBadRequest.WithCause(apperror.New(40000, "feedback 必须为 suitable/not_suitable/pending", 400))
	}
	if err := s.repos.Interaction().Insert(&model.InteractionLog{
		ID: uuid.NewString(), TenantID: tenantID, SessionID: sessionID,
		UserID: userID, EventType: "feedback", TargetID: candidateID,
		JobID: jobID, Feedback: feedback,
	}); err != nil {
		return err
	}
	// 偏好计数（Redis 不可用时静默降级：反馈已落库，个性化暂失效）
	if s.rdb != nil {
		delta := 0.0
		switch feedback {
		case FeedbackSuitable:
			delta = prefDelta
		case FeedbackNotSuitable:
			delta = -prefDelta
		}
		key := fmt.Sprintf(prefsKeyFmt, userID)
		s.rdb.HIncrByFloat(ctx, key, "boost", delta)
		s.rdb.Expire(ctx, key, 30*24*time.Hour)
	}
	return nil
}

// PersonalizedBoost 读取用户个性化系数（clamp 后返回）。
func (s *FeedbackService) PersonalizedBoost(ctx context.Context, userID string) float64 {
	if s.rdb == nil {
		return 0
	}
	val, err := s.rdb.HGet(ctx, fmt.Sprintf(prefsKeyFmt, userID), "boost").Float64()
	if err != nil {
		return 0
	}
	return math.Max(-boostClamp, math.Min(boostClamp, val))
}

// ApplyBoost 读时个性化：score * (1 + boost)，限制在 [0, 100]，保留两位小数（避免浮点噪声）。
func (s *FeedbackService) ApplyBoost(score float64, boost float64) float64 {
	adjusted := score * (1 + boost)
	clamped := math.Max(0, math.Min(100, adjusted))
	return math.Round(clamped*100) / 100
}

// SessionMemory 会话记忆（Redis，TTL 24h）。
type SessionMemory struct {
	rdb *redis.Client
}

func NewSessionMemory(rdb *redis.Client) *SessionMemory { return &SessionMemory{rdb: rdb} }

const sessionTTL = 24 * time.Hour

func (m *SessionMemory) Save(ctx context.Context, sessionID string, state map[string]any) error {
	if m.rdb == nil {
		return nil
	}
	data, err := json.Marshal(state)
	if err != nil {
		return err
	}
	return m.rdb.Set(ctx, "session:"+sessionID, data, sessionTTL).Err()
}

func (m *SessionMemory) Load(ctx context.Context, sessionID string) (map[string]any, error) {
	if m.rdb == nil {
		return nil, nil
	}
	data, err := m.rdb.Get(ctx, "session:"+sessionID).Bytes()
	if err == redis.Nil {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var state map[string]any
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, err
	}
	return state, nil
}
