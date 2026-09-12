// Package model 定义 GORM 实体与业务 DTO。
package model

import (
	"database/sql/driver"
	"encoding/json"
	"errors"
	"time"
)

// JSON 通用 JSON 列类型。
type JSON map[string]interface{}

func (j JSON) Value() (driver.Value, error) {
	if j == nil {
		return nil, nil
	}
	return json.Marshal(j)
}

func (j *JSON) Scan(value interface{}) error {
	if value == nil {
		*j = nil
		return nil
	}
	b, ok := value.([]byte)
	if !ok {
		return errors.New("JSON scan: unsupported type")
	}
	return json.Unmarshal(b, j)
}

// StringSlice JSON 字符串数组列。
type StringSlice []string

func (s StringSlice) Value() (driver.Value, error) {
	if s == nil {
		return "[]", nil
	}
	return json.Marshal(s)
}

func (s *StringSlice) Scan(value interface{}) error {
	if value == nil {
		*s = nil
		return nil
	}
	b, ok := value.([]byte)
	if !ok {
		return errors.New("StringSlice scan: unsupported type")
	}
	return json.Unmarshal(b, s)
}

// ---- 实体 ----

type User struct {
	ID           string    `gorm:"column:id;size:36;primaryKey" json:"id"`
	TenantID     string    `gorm:"column:tenant_id;size:64;index:idx_tenant_username,priority:1" json:"tenant_id"`
	Username     string    `gorm:"column:username;size:64;index:idx_tenant_username,priority:2" json:"username"`
	PasswordHash string    `gorm:"column:password_hash;size:128" json:"-"`
	Role         string    `gorm:"column:role;size:16" json:"role"`
	CreatedAt    time.Time `gorm:"column:created_at;autoCreateTime" json:"created_at"`
}

func (User) TableName() string { return "users" }

type Job struct {
	ID          string    `gorm:"column:id;size:36;primaryKey" json:"id"`
	TenantID    string    `gorm:"column:tenant_id;size:64;index" json:"tenant_id"`
	Title       string    `gorm:"column:title;size:256" json:"title"`
	JDText      string    `gorm:"column:jd_text;type:text" json:"jd_text"`
	JDJSON      JSON      `gorm:"column:jd_json;type:json" json:"jd_json"`
	JobCategory string    `gorm:"column:job_category;size:32" json:"job_category"`
	// WeightsOverride 岗位级仲裁权重覆盖，形如 {"skill_evaluator":0.4,...}；
	// 为空表示用类别默认权重。用 JSON 列而不是多个字段：权重维度随专家组变化。
	WeightsOverride JSON `gorm:"column:weights_override;type:json" json:"weights_override,omitempty"`
	// ScreenOverrides 岗位级检索/重排参数覆盖（rag_top_k / rerank_threshold / rerank_mode / chunk_size 等）
	ScreenOverrides JSON      `gorm:"column:screen_overrides;type:json" json:"screen_overrides,omitempty"`
	CreatedAt       time.Time `gorm:"column:created_at;autoCreateTime" json:"created_at"`
}

func (Job) TableName() string { return "jobs" }

type Candidate struct {
	ID             string    `gorm:"column:id;size:36;primaryKey" json:"id"`
	TenantID       string    `gorm:"column:tenant_id;size:64;index;uniqueIndex:uk_tenant_email,priority:1" json:"tenant_id"`
	Name           string    `gorm:"column:name;size:128" json:"name"`
	Email          string    `gorm:"column:email;size:256;uniqueIndex:uk_tenant_email,priority:2" json:"email"`
	Phone          string    `gorm:"column:phone;size:32" json:"phone"`
	ResumeText     string    `gorm:"column:resume_text;type:mediumtext" json:"resume_text"`
	StructuredJSON JSON      `gorm:"column:structured_json;type:json" json:"structured_json"`
	EmbeddingID    string    `gorm:"column:embedding_id;size:128" json:"embedding_id"`
	// ProfileHash 简历内容指纹：重复筛选时用来判断能否复用既有精筛结论
	ProfileHash    string    `gorm:"column:profile_hash;size:64;index" json:"profile_hash,omitempty"`
	CreatedAt      time.Time `gorm:"column:created_at;autoCreateTime" json:"created_at"`
}

func (Candidate) TableName() string { return "candidates" }

type MatchResult struct {
	ID                 string      `gorm:"column:id;size:36;primaryKey" json:"id"`
	TenantID           string      `gorm:"column:tenant_id;size:64;index:idx_tenant_job,priority:1;uniqueIndex:uk_job_candidate,priority:1" json:"tenant_id"`
	JobID              string      `gorm:"column:job_id;size:36;index:idx_tenant_job,priority:2;uniqueIndex:uk_job_candidate,priority:2" json:"job_id"`
	CandidateID        string      `gorm:"column:candidate_id;size:36;uniqueIndex:uk_job_candidate,priority:3" json:"candidate_id"`
	TaskID             string      `gorm:"column:task_id;size:36" json:"task_id"`
	OverallScore       float64     `gorm:"column:overall_score;type:decimal(6,2)" json:"overall_score"`
	DimensionScores    JSON        `gorm:"column:dimension_scores;type:json" json:"dimension_scores"`
	RecommendationText string      `gorm:"column:recommendation_text;type:text" json:"recommendation_text"`
	Evidence           StringSlice `gorm:"column:evidence;type:json" json:"evidence"`
	DiscussionJSON     JSON        `gorm:"column:discussion_json;type:json" json:"discussion_json"`
	// ProfileHash 本次结果对应的简历指纹：重筛时指纹一致则复用（幂等缓存）
	ProfileHash        string      `gorm:"column:profile_hash;size:64" json:"profile_hash,omitempty"`
	// ConfigHash 本次结果对应的岗位配置指纹（权重/检索参数/JD）：
	// 只比对简历指纹会在"改了岗位配置"后错误复用旧结论，必须一起比对。
	ConfigHash         string      `gorm:"column:config_hash;size:64" json:"config_hash,omitempty"`
	CreatedAt          time.Time   `gorm:"column:created_at;autoCreateTime" json:"created_at"`
	UpdatedAt          time.Time   `gorm:"column:updated_at;autoUpdateTime" json:"updated_at"`
}

func (MatchResult) TableName() string { return "match_results" }

type InteractionLog struct {
	ID              string    `gorm:"column:id;size:36;primaryKey" json:"id"`
	TenantID        string    `gorm:"column:tenant_id;size:64;index:idx_tenant_session,priority:1" json:"tenant_id"`
	SessionID       string    `gorm:"column:session_id;size:64;index:idx_tenant_session,priority:2" json:"session_id"`
	UserID          string    `gorm:"column:user_id;size:36" json:"user_id"`
	EventType       string    `gorm:"column:event_type;size:64" json:"event_type"`
	TargetID        string    `gorm:"column:target_id;size:128" json:"target_id"`
	JobID           string    `gorm:"column:job_id;size:36" json:"job_id"`
	Feedback        string    `gorm:"column:feedback;size:32" json:"feedback"`
	SummaryVectorID string    `gorm:"column:summary_vector_id;size:128" json:"summary_vector_id"`
	CreatedAt       time.Time `gorm:"column:created_at;autoCreateTime" json:"created_at"`
}

func (InteractionLog) TableName() string { return "interaction_log" }

type CostRecord struct {
	ID               string    `gorm:"column:id;size:36;primaryKey" json:"id"`
	TenantID         string    `gorm:"column:tenant_id;size:64;index:idx_tenant_created,priority:1" json:"tenant_id"`
	TraceID          string    `gorm:"column:trace_id;size:64;index:idx_tenant_created,priority:2" json:"trace_id"`
	ModelName        string    `gorm:"column:model_name;size:128" json:"model_name"`
	TokensPrompt     int       `gorm:"column:tokens_prompt" json:"tokens_prompt"`
	TokensCompletion int       `gorm:"column:tokens_completion" json:"tokens_completion"`
	Cost             float64   `gorm:"column:cost;type:decimal(12,6)" json:"cost"`
	CreatedAt        time.Time `gorm:"column:created_at;autoCreateTime" json:"created_at"`
}

func (CostRecord) TableName() string { return "cost_records" }

// ScreeningTask 异步筛选任务（v5 新增）。
type ScreeningTask struct {
	ID            string    `gorm:"column:id;size:36;primaryKey" json:"id"`
	TenantID      string    `gorm:"column:tenant_id;size:64;index:idx_tenant_job,priority:1" json:"tenant_id"`
	JobID         string    `gorm:"column:job_id;size:36;index:idx_tenant_job,priority:2" json:"job_id"`
	UserID        string    `gorm:"column:user_id;size:36" json:"user_id"`
	SessionID     string    `gorm:"column:session_id;size:64" json:"session_id"`
	Status        string    `gorm:"column:status;size:16" json:"status"` // pending/running/succeeded/failed
	Progress      int       `gorm:"column:progress" json:"progress"`     // 0-100
	CandidatesN   int       `gorm:"column:candidates_n" json:"candidates_n"`
	ErrorMsg      string    `gorm:"column:error_msg;size:512" json:"error_msg"`
	CreatedAt     time.Time `gorm:"column:created_at;autoCreateTime" json:"created_at"`
	UpdatedAt     time.Time `gorm:"column:updated_at;autoUpdateTime" json:"updated_at"`
}

func (ScreeningTask) TableName() string { return "screening_tasks" }

// 任务状态枚举。
const (
	TaskStatusPending   = "pending"
	TaskStatusRunning   = "running"
	TaskStatusSucceeded = "succeeded"
	TaskStatusFailed    = "failed"
)
