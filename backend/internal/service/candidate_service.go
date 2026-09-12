package service

import (
	"bytes"
	"context"
	"path/filepath"
	"strings"

	"github.com/google/uuid"

	"github.com/ai-recruitment/backend/internal/agenttypes"
	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/agentclient"
	"github.com/ai-recruitment/backend/internal/pkg/fingerprint"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/logger"
	"github.com/ai-recruitment/backend/internal/repository"
)

// CandidateService 候选人管理：上传时调 agent 解析并写向量库。
type CandidateService struct {
	repos     *repository.Repos
	agent     *agentclient.Client
	maxBytes  int64
	allowExt  map[string]struct{}
}

func NewCandidateService(repos *repository.Repos, agent *agentclient.Client, maxBytes int64, allowedExt []string) *CandidateService {
	allow := make(map[string]struct{}, len(allowedExt))
	for _, e := range allowedExt {
		allow[strings.ToLower(e)] = struct{}{}
	}
	return &CandidateService{repos: repos, agent: agent, maxBytes: maxBytes, allowExt: allow}
}

// validateFile 扩展名白名单 + 大小 + 魔数签名三重校验。
func (s *CandidateService) validateFile(filename string, content []byte) error {
	ext := strings.ToLower(filepath.Ext(filename))
	if _, ok := s.allowExt[ext]; !ok {
		return apperror.ErrUploadInvalid.WithCause(apperror.New(40001, "仅支持 pdf/png/jpg/jpeg", 400))
	}
	if int64(len(content)) > s.maxBytes {
		return apperror.ErrUploadInvalid
	}
	if len(content) < 8 {
		return apperror.ErrUploadInvalid.WithCause(apperror.New(40001, "文件内容过短", 400))
	}
	switch ext {
	case ".pdf":
		if !bytes.HasPrefix(content, []byte("%PDF")) {
			return apperror.ErrUploadInvalid.WithCause(apperror.New(40001, "PDF 魔数校验失败", 400))
		}
	case ".png":
		if !bytes.HasPrefix(content, []byte{0x89, 0x50, 0x4E, 0x47}) {
			return apperror.ErrUploadInvalid.WithCause(apperror.New(40001, "PNG 魔数校验失败", 400))
		}
	case ".jpg", ".jpeg":
		if !bytes.HasPrefix(content, []byte{0xFF, 0xD8, 0xFF}) {
			return apperror.ErrUploadInvalid.WithCause(apperror.New(40001, "JPEG 魔数校验失败", 400))
		}
	}
	return nil
}

// Upload 简历上传：校验 → agent 解析（含向量化）→ 落库。
func (s *CandidateService) Upload(ctx context.Context, tenantID, filename string, content []byte) (*model.Candidate, *agenttypes.CandidateProfile, error) {
	if err := s.validateFile(filename, content); err != nil {
		return nil, nil, err
	}

	candidateID := uuid.NewString()
	var profile agenttypes.CandidateProfile
	err := s.agent.PostMultipart(ctx, "/parse/resume", "file", filename, content, map[string]string{
		"tenant_id":    tenantID,
		"candidate_id": candidateID,
	}, &profile)
	if err != nil {
		return nil, nil, err
	}
	if profile.Email == "" {
		return nil, nil, apperror.ErrBadRequest.WithCause(apperror.New(40002, "简历解析未获得有效邮箱，无法建档", 400))
	}

	structured := profileToJSON(&profile)
	candidate := &model.Candidate{
		ID:             candidateID,
		TenantID:       tenantID,
		Name:           profile.Name,
		Email:          profile.Email,
		Phone:          profile.Phone,
		ResumeText:     profile.RawText,
		EmbeddingID:    candidateID,
		StructuredJSON: structured,
		// 简历指纹：重筛时可判断"这份简历是否已经精筛过"，避免重复烧 LLM
		ProfileHash: fingerprint.Of(profile.RawText, structured),
	}
	if err := s.repos.Candidate().Upsert(candidate); err != nil {
		return nil, nil, err
	}
	logger.L(ctx).Info().Str("candidate_id", candidate.ID).Str("email", candidate.Email).Msg("candidate uploaded")
	return candidate, &profile, nil
}

func (s *CandidateService) List(tenantID string) ([]model.Candidate, error) {
	return s.repos.Candidate().List(tenantID)
}

// Delete 删除候选人（向量清理由 agent 侧 best-effort）。
func (s *CandidateService) Delete(ctx context.Context, tenantID, id string) error {
	if _, err := s.repos.Candidate().FindByID(tenantID, id); err != nil {
		return err
	}
	if err := s.repos.Candidate().Delete(tenantID, id); err != nil {
		return err
	}
	_ = s.agent.PostJSON(ctx, "/vectors/delete", map[string]string{
		"tenant_id": tenantID, "candidate_id": id,
	}, nil)
	return nil
}

func profileToJSON(p *agenttypes.CandidateProfile) model.JSON {
	we := make([]interface{}, 0, len(p.WorkExperience))
	for _, w := range p.WorkExperience {
		we = append(we, map[string]interface{}{
			"company": w.Company, "title": w.Title,
			"start_date": w.StartDate, "end_date": w.EndDate, "description": w.Description,
		})
	}
	ed := make([]interface{}, 0, len(p.Education))
	for _, e := range p.Education {
		ed = append(ed, map[string]interface{}{
			"school": e.School, "degree": e.Degree, "major": e.Major,
			"start_date": e.StartDate, "end_date": e.EndDate,
		})
	}
	skills := make([]interface{}, 0, len(p.Skills))
	for _, sk := range p.Skills {
		skills = append(skills, sk)
	}
	return model.JSON{
		"name": p.Name, "email": p.Email, "phone": p.Phone,
		"work_experience": we, "education": ed, "skills": skills,
	}
}
