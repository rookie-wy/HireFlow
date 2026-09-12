package repository

import (
	"errors"

	"gorm.io/gorm"

	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
)

// JobRepo 岗位仓储。
type JobRepo struct{ db *gorm.DB }

func (r *Repos) Job() *JobRepo { return &JobRepo{r.db} }

func (r *JobRepo) Insert(job *model.Job) error {
	if err := r.db.Create(job).Error; err != nil {
		return apperror.ErrDatabase.WithCause(err)
	}
	return nil
}

func (r *JobRepo) FindByID(tenantID, id string) (*model.Job, error) {
	var job model.Job
	err := r.db.Where("tenant_id = ? AND id = ?", tenantID, id).First(&job).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, apperror.ErrNotFound
	}
	if err != nil {
		return nil, apperror.ErrDatabase.WithCause(err)
	}
	return &job, nil
}

func (r *JobRepo) List(tenantID string) ([]model.Job, error) {
	var jobs []model.Job
	err := r.db.Where("tenant_id = ?", tenantID).Order("created_at DESC").Find(&jobs).Error
	return jobs, err
}

// UpdateOverrides 更新岗位级配置（部分更新：只写传入的列）。
func (r *JobRepo) UpdateOverrides(tenantID, jobID string, patch map[string]any) error {
	res := r.db.Model(&model.Job{}).Where("tenant_id = ? AND id = ?", tenantID, jobID).Updates(patch)
	if res.Error != nil {
		return apperror.ErrDatabase.WithCause(res.Error)
	}
	if res.RowsAffected == 0 {
		// 值未变化时 RowsAffected 也可能为 0，这里只在记录不存在时报错
		var count int64
		if err := r.db.Model(&model.Job{}).Where("tenant_id = ? AND id = ?", tenantID, jobID).
			Count(&count).Error; err != nil {
			return apperror.ErrDatabase.WithCause(err)
		}
		if count == 0 {
			return apperror.ErrNotFound
		}
	}
	return nil
}

func (r *JobRepo) Delete(tenantID, id string) error {
	res := r.db.Where("tenant_id = ? AND id = ?", tenantID, id).Delete(&model.Job{})
	if res.Error != nil {
		return apperror.ErrDatabase.WithCause(res.Error)
	}
	if res.RowsAffected == 0 {
		return apperror.ErrNotFound
	}
	return nil
}

// CandidateRepo 候选人仓储。
type CandidateRepo struct{ db *gorm.DB }

func (r *Repos) Candidate() *CandidateRepo { return &CandidateRepo{r.db} }

// Upsert 按 (tenant_id, email) 幂等写入。
func (r *CandidateRepo) Upsert(c *model.Candidate) error {
	var existing model.Candidate
	err := r.db.Where("tenant_id = ? AND email = ?", c.TenantID, c.Email).First(&existing).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		if err := r.db.Create(c).Error; err != nil {
			return apperror.ErrDatabase.WithCause(err)
		}
		return nil
	}
	if err != nil {
		return apperror.ErrDatabase.WithCause(err)
	}
	// 覆盖更新（保留原 ID）
	c.ID = existing.ID
	c.CreatedAt = existing.CreatedAt
	return r.db.Model(&existing).Updates(map[string]interface{}{
		"name":            c.Name,
		"phone":           c.Phone,
		"resume_text":     c.ResumeText,
		"structured_json": c.StructuredJSON,
		"embedding_id":    c.EmbeddingID,
		// 注意：新增字段必须同步加到这里，否则"重新上传简历"不会刷新指纹（踩过一次）
		"profile_hash": c.ProfileHash,
	}).Error
}

func (r *CandidateRepo) FindByID(tenantID, id string) (*model.Candidate, error) {
	var c model.Candidate
	err := r.db.Where("tenant_id = ? AND id = ?", tenantID, id).First(&c).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, apperror.ErrNotFound
	}
	if err != nil {
		return nil, apperror.ErrDatabase.WithCause(err)
	}
	return &c, nil
}

func (r *CandidateRepo) List(tenantID string) ([]model.Candidate, error) {
	var candidates []model.Candidate
	err := r.db.Where("tenant_id = ?", tenantID).Order("created_at DESC").Find(&candidates).Error
	return candidates, err
}

// DefaultScreeningPageSize 分页加载候选人的默认页大小。
const DefaultScreeningPageSize = 200

// CountByTenant 租户候选人总数（用于判断是否需要分批）。
func (r *CandidateRepo) CountByTenant(tenantID string) (int64, error) {
	var n int64
	err := r.db.Model(&model.Candidate{}).Where("tenant_id = ?", tenantID).Count(&n).Error
	return n, err
}

// ListPage 分页加载候选人（按创建时间倒序、id 次序稳定，避免翻页漏人/重复）。
func (r *CandidateRepo) ListPage(tenantID string, offset, limit int) ([]model.Candidate, error) {
	if limit <= 0 {
		limit = DefaultScreeningPageSize
	}
	var candidates []model.Candidate
	err := r.db.Where("tenant_id = ?", tenantID).
		Order("created_at DESC, id ASC").Offset(offset).Limit(limit).Find(&candidates).Error
	return candidates, err
}

// LoadForScreening 加载筛选载荷。
// 兼容旧调用：limit<=0 时按默认页大小加载第一页；
// limit 超过 200 时按需分页取满（不再静默截断到 200 人）。
func (r *CandidateRepo) LoadForScreening(tenantID string, limit int) ([]model.Candidate, error) {
	if limit <= 0 {
		limit = DefaultScreeningPageSize
	}
	if limit <= DefaultScreeningPageSize {
		return r.ListPage(tenantID, 0, limit)
	}
	out := make([]model.Candidate, 0, limit)
	for offset := 0; offset < limit; offset += DefaultScreeningPageSize {
		pageSize := DefaultScreeningPageSize
		if remain := limit - offset; remain < pageSize {
			pageSize = remain
		}
		page, err := r.ListPage(tenantID, offset, pageSize)
		if err != nil {
			return nil, err
		}
		out = append(out, page...)
		if len(page) < pageSize {
			break
		}
	}
	return out, nil
}

func (r *CandidateRepo) Delete(tenantID, id string) error {
	res := r.db.Where("tenant_id = ? AND id = ?", tenantID, id).Delete(&model.Candidate{})
	if res.Error != nil {
		return apperror.ErrDatabase.WithCause(res.Error)
	}
	if res.RowsAffected == 0 {
		return apperror.ErrNotFound
	}
	return nil
}
