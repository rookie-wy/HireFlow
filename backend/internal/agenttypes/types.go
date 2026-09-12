// Package agenttypes backend 与 agent 服务共享的数据契约。
// 字段与 agent(Python) 端 Pydantic 模型一一对应。
package agenttypes

// JobDescription JD 解析结果。
type JobDescription struct {
	Title            string   `json:"title"`
	HardRequirements []string `json:"hard_requirements"`
	SoftRequirements []string `json:"soft_requirements"`
	SkillGraph       []string `json:"skill_graph"`
	JobCategory      string   `json:"job_category"` // tech|management|design|general
}

// WorkExperience 工作经历。
type WorkExperience struct {
	Company     string `json:"company"`
	Title       string `json:"title"`
	StartDate   string `json:"start_date"`
	EndDate     string `json:"end_date,omitempty"`
	Description string `json:"description,omitempty"`
}

// Education 教育经历。
type Education struct {
	School    string `json:"school"`
	Degree    string `json:"degree"`
	Major     string `json:"major,omitempty"`
	StartDate string `json:"start_date,omitempty"`
	EndDate   string `json:"end_date,omitempty"`
}

// CandidateProfile 简历解析结果。
type CandidateProfile struct {
	Name           string           `json:"name"`
	Email          string           `json:"email"`
	Phone          string           `json:"phone"`
	WorkExperience []WorkExperience `json:"work_experience"`
	Education      []Education      `json:"education"`
	Skills         []string         `json:"skills"`
	RawText        string           `json:"raw_text"`
}

// ScreeningCandidate 筛选请求中的候选人载荷（agent 无状态，数据由请求传入）。
type ScreeningCandidate struct {
	CandidateID    string          `json:"candidate_id"`
	ResumeText     string          `json:"resume_text"`
	StructuredJSON map[string]any  `json:"structured_json"`
}

// ScreeningConfig 筛选参数。
type ScreeningConfig struct {
	MaxCandidates int      `json:"max_candidates"`
	Query         string   `json:"query,omitempty"`
	EnableHyde    bool     `json:"enable_hyde"`
	Weights       string   `json:"weights_profile,omitempty"`
}

// AgentEvaluationResult 单个 Agent 评估结果。
type AgentEvaluationResult struct {
	Agent           string          `json:"agent"`
	Score           float64         `json:"score"`
	DimensionScores map[string]float64 `json:"dimension_scores"`
	Evidence        []string        `json:"evidence"`
	Confidence      float64         `json:"confidence"`
}

// OverallReport 精筛综合报告。
type OverallReport struct {
	CandidateID        string                `json:"candidate_id"`
	OverallScore       float64               `json:"overall_score"`
	DimensionScores    map[string]float64    `json:"dimension_scores"`
	RecommendationText string                `json:"recommendation_text"`
	Evidence           []string              `json:"evidence"`
	AgentDetails       []AgentEvaluationResult `json:"agent_details"`
	Discussion         map[string]any        `json:"discussion,omitempty"`
}

// InterviewDraft 面试邀请草稿。
type InterviewDraft struct {
	CandidateEmail string   `json:"candidate_email"`
	Subject        string   `json:"subject"`
	Body           string   `json:"body"`
	ProposedTimes  []string `json:"proposed_times"`
}

// ReplyIntent 回复意图分析。
type ReplyIntent struct {
	Intent   string   `json:"intent"` // accept|propose_new_time|decline
	NewTimes []string `json:"new_times,omitempty"`
	Message  string   `json:"message,omitempty"`
}

// CostUsage LLM 成本计量（agent 事件中回传，backend 落库）。
type CostUsage struct {
	ModelName        string  `json:"model_name"`
	TokensPrompt     int     `json:"tokens_prompt"`
	TokensCompletion int     `json:"tokens_completion"`
	Cost             float64 `json:"cost"`
}


// WeightsByCategory 各类别的默认仲裁权重（与 agent/app/agents/registry.py 保持一致）。
// backend 用它校验岗位级权重覆盖的合法性；**改动时必须与 agent 侧同步**。
var WeightsByCategory = map[string]map[string]float64{
	"tech":       {"interviewer": 0.35, "skill_evaluator": 0.35, "culture_fit": 0.15, "stability_analyzer": 0.15},
	"management": {"interviewer": 0.35, "leadership": 0.35, "culture_fit": 0.15, "stability_analyzer": 0.15},
	"design":     {"interviewer": 0.30, "skill_evaluator": 0.25, "visual_evaluator": 0.15, "culture_fit": 0.15, "stability_analyzer": 0.15},
	"general":    {"interviewer": 0.50, "culture_fit": 0.30, "stability_analyzer": 0.20},
}

// AllowedScreenOverrides 允许按岗位覆盖的检索/重排参数白名单（与 agent Settings 字段同名）。
var AllowedScreenOverrides = map[string]bool{
	"rag_top_k":            true,
	"rerank_threshold":     true,
	"rerank_threshold_cosine": true,
	"rerank_mode":          true,
	"rerank_pairs_factor":  true,
	"rerank_doc_chars":     true,
	"chunk_size":           true,
	"enable_hyde":          true,
}
