package repository

import (
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"

	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
)

// MatchRepo 匹配结果仓储。
type MatchRepo struct{ db *gorm.DB }

func (r *Repos) Match() *MatchRepo { return &MatchRepo{r.db} }

// InsertBatch 批量写入匹配结果（幂等：同租户+岗位+候选人已存在则覆盖更新）。
// 依赖唯一键 uk_job_candidate，重复筛选不会堆积重复行。
func (r *MatchRepo) InsertBatch(results []model.MatchResult) error {
	if len(results) == 0 {
		return nil
	}
	err := r.db.Clauses(clause.OnConflict{
		Columns: []clause.Column{{Name: "tenant_id"}, {Name: "job_id"}, {Name: "candidate_id"}},
		DoUpdates: clause.AssignmentColumns([]string{
			"task_id", "overall_score", "dimension_scores", "recommendation_text",
			"evidence", "discussion_json", "profile_hash", "config_hash", "updated_at",
		}),
	}).Create(&results).Error
	if err != nil {
		return apperror.ErrDatabase.WithCause(err)
	}
	return nil
}

// ListByJobIDs 按岗位列出匹配结果（用于幂等缓存命中判断）。
func (r *MatchRepo) ListByJobIDs(tenantID, jobID string) ([]model.MatchResult, error) {
	var results []model.MatchResult
	err := r.db.Where("tenant_id = ? AND job_id = ?", tenantID, jobID).
		Order("overall_score DESC").Find(&results).Error
	if err != nil {
		return nil, apperror.ErrDatabase.WithCause(err)
	}
	return results, nil
}

// CachedVerdict 已有精筛结论（幂等缓存条目）。
type CachedVerdict struct {
	ProfileHash        string                 `json:"profile_hash"`
	ConfigHash         string                 `json:"config_hash"`
	OverallScore       float64                `json:"overall_score"`
	DimensionScores    map[string]interface{} `json:"dimension_scores"`
	RecommendationText string                 `json:"recommendation_text"`
	Evidence           []string               `json:"evidence"`
	Discussion         map[string]interface{} `json:"discussion_json"`
}

// CachedVerdicts 返回岗位下已有结论的候选人缓存（key = candidate_id）。
// 只返回带指纹的行——没有指纹的历史数据无法判断是否仍然有效，宁可重算。
func (r *MatchRepo) CachedVerdicts(tenantID, jobID string) (map[string]CachedVerdict, error) {
	rows, err := r.ListByJobIDs(tenantID, jobID)
	if err != nil {
		return nil, err
	}
	out := make(map[string]CachedVerdict, len(rows))
	for _, m := range rows {
		if m.ProfileHash == "" {
			continue
		}
		dims := map[string]interface{}{}
		for k, v := range m.DimensionScores {
			dims[k] = v
		}
		disc := map[string]interface{}{}
		for k, v := range m.DiscussionJSON {
			disc[k] = v
		}
		out[m.CandidateID] = CachedVerdict{
			ProfileHash:        m.ProfileHash,
			ConfigHash:         m.ConfigHash,
			OverallScore:       m.OverallScore,
			DimensionScores:    dims,
			RecommendationText: m.RecommendationText,
			Evidence:           []string(m.Evidence),
			Discussion:         disc,
		}
	}
	return out, nil
}

func (r *MatchRepo) ListByJob(tenantID, jobID string) ([]model.MatchResult, error) {
	var results []model.MatchResult
	err := r.db.Where("tenant_id = ? AND job_id = ?", tenantID, jobID).
		Order("overall_score DESC").Find(&results).Error
	return results, err
}

func (r *MatchRepo) DeleteByTask(tenantID, taskID string) error {
	return r.db.Where("tenant_id = ? AND task_id = ?", tenantID, taskID).Delete(&model.MatchResult{}).Error
}

// InteractionRepo 交互日志仓储。
type InteractionRepo struct{ db *gorm.DB }

func (r *Repos) Interaction() *InteractionRepo { return &InteractionRepo{r.db} }

func (r *InteractionRepo) Insert(log *model.InteractionLog) error {
	if log.ID == "" {
		log.ID = uuid.NewString()
	}
	if err := r.db.Create(log).Error; err != nil {
		return apperror.ErrDatabase.WithCause(err)
	}
	return nil
}

func (r *InteractionRepo) ListByJob(tenantID, jobID string, limit int) ([]model.InteractionLog, error) {
	var logs []model.InteractionLog
	if limit <= 0 {
		limit = 100
	}
	err := r.db.Where("tenant_id = ? AND job_id = ?", tenantID, jobID).
		Order("created_at DESC").Limit(limit).Find(&logs).Error
	return logs, err
}

// HighPotentialIDs 历史标记「合适」的候选人（排除当前岗位）。
func (r *InteractionRepo) HighPotentialIDs(tenantID string, excludeJobID string, limit int) ([]string, error) {
	if limit <= 0 {
		limit = 5
	}
	var ids []string
	sub := r.db.Model(&model.InteractionLog{}).Select("target_id").
		Where("tenant_id = ? AND job_id = ? AND feedback = ?", tenantID, excludeJobID, "not_suitable")
	err := r.db.Model(&model.InteractionLog{}).Select("DISTINCT target_id").
		Where("tenant_id = ? AND feedback = ? AND target_id NOT IN (?)", tenantID, "suitable", sub).
		Limit(limit).Scan(&ids).Error
	return ids, err
}

// CostRepo 成本记录仓储。
type CostRepo struct{ db *gorm.DB }

func (r *Repos) Cost() *CostRepo { return &CostRepo{r.db} }

func (r *CostRepo) InsertBatch(records []model.CostRecord) error {
	if len(records) == 0 {
		return nil
	}
	for i := range records {
		if records[i].ID == "" {
			records[i].ID = uuid.NewString()
		}
	}
	if err := r.db.Create(&records).Error; err != nil {
		return apperror.ErrDatabase.WithCause(err)
	}
	return nil
}

func (r *CostRepo) SummarizeByTenant(tenantID string) ([]map[string]interface{}, error) {
	var rows []map[string]interface{}
	err := r.db.Model(&model.CostRecord{}).
		Select("model_name, COUNT(*) as calls, SUM(tokens_prompt) as prompt_tokens, SUM(tokens_completion) as completion_tokens, SUM(cost) as total_cost").
		Where("tenant_id = ?", tenantID).
		Group("model_name").Find(&rows).Error
	return rows, err
}

// TaskRepo 筛选任务仓储。
type TaskRepo struct{ db *gorm.DB }

func (r *Repos) Task() *TaskRepo { return &TaskRepo{r.db} }

func (r *TaskRepo) Create(task *model.ScreeningTask) error {
	if err := r.db.Create(task).Error; err != nil {
		return apperror.ErrDatabase.WithCause(err)
	}
	return nil
}

func (r *TaskRepo) FindByID(tenantID, id string) (*model.ScreeningTask, error) {
	var t model.ScreeningTask
	err := r.db.Where("tenant_id = ? AND id = ?", tenantID, id).First(&t).Error
	return &t, err
}

func (r *TaskRepo) Update(t *model.ScreeningTask) error {
	return r.db.Model(t).Updates(map[string]interface{}{
		"status": t.Status, "progress": t.Progress, "error_msg": t.ErrorMsg,
	}).Error
}
