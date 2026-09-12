package service

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/ai-recruitment/backend/internal/agenttypes"
	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/agentclient"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/logger"
	"github.com/ai-recruitment/backend/internal/repository"
)

// JobService 岗位管理：创建时调 agent 解析 JD。
type JobService struct {
	repos *repository.Repos
	agent *agentclient.Client
}

func NewJobService(repos *repository.Repos, agent *agentclient.Client) *JobService {
	return &JobService{repos: repos, agent: agent}
}

type CreateJobResult struct {
	Job    *model.Job                    `json:"job"`
	Parsed *agenttypes.JobDescription    `json:"parsed"`
}

func (s *JobService) Create(ctx context.Context, tenantID, jdText, language string) (*CreateJobResult, error) {
	if jdText == "" {
		return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000, "jd_text 必填", 400))
	}
	var parsed agenttypes.JobDescription
	err := s.agent.PostJSON(ctx, "/parse/jd", map[string]string{
		"jd_text":  jdText,
		"language": language,
	}, &parsed)
	if err != nil {
		return nil, err
	}
	if parsed.JobCategory == "" {
		parsed.JobCategory = "general"
	}
	job := &model.Job{
		ID:          uuid.NewString(),
		TenantID:    tenantID,
		Title:       parsed.Title,
		JDText:      jdText,
		JDJSON: model.JSON{
			"hard_requirements": toAnySlice(parsed.HardRequirements),
			"soft_requirements": toAnySlice(parsed.SoftRequirements),
			"skill_graph":       toAnySlice(parsed.SkillGraph),
			"job_category":      parsed.JobCategory,
		},
		JobCategory: parsed.JobCategory,
	}
	if err := s.repos.Job().Insert(job); err != nil {
		return nil, err
	}
	logger.L(ctx).Info().Str("job_id", job.ID).Str("category", job.JobCategory).Msg("job created")
	return &CreateJobResult{Job: job, Parsed: &parsed}, nil
}

// UpdateOverrides 设置岗位级配置（O7）。
// 校验规则：权重键必须在专家组内、值在 (0,1]、总和接近 1；
//       检索参数只允许白名单键，避免把任意 JSON 透传给 agent 造成隐式行为变更。
func (s *JobService) UpdateOverrides(ctx context.Context, tenantID, jobID string,
	weights map[string]float64, screen map[string]any) (*model.Job, error) {

	job, err := s.repos.Job().FindByID(tenantID, jobID)
	if err != nil {
		return nil, err
	}
	if len(weights) > 0 {
		allowed := agenttypes.WeightsByCategory[job.JobCategory]
		if len(allowed) == 0 {
			allowed = agenttypes.WeightsByCategory["general"]
		}
		sum := 0.0
		for agent, w := range weights {
			if _, ok := allowed[agent]; !ok {
				return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000,
					"权重包含该岗位专家组之外的专家: "+agent, 400))
			}
			if w <= 0 || w > 1 {
				return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000,
					"权重必须在 (0,1] 之间: "+agent, 400))
			}
			sum += w
		}
		if sum < 0.99 || sum > 1.01 {
			return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000,
				fmt.Sprintf("权重之和必须为 1（当前 %.3f）", sum), 400))
		}
	}
	for k, v := range screen {
		if !agenttypes.AllowedScreenOverrides[k] {
			return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000,
				"不支持的检索参数: "+k, 400))
		}
		if _, ok := v.(float64); !ok {
			if _, isStr := v.(string); !isStr {
				return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000,
					"检索参数值必须是数字或字符串: "+k, 400))
			}
		}
	}

	// 注意：GORM 的 Updates(map) 会把值直接交给 driver，
	// 原生 map[string]float64 不被支持（unsupported type ... a map），
	// 必须转成实现了 driver.Valuer 的 model.JSON。
	patch := map[string]any{}
	if weights != nil {
		wj := model.JSON{}
		for k, v := range weights {
			wj[k] = v
		}
		patch["weights_override"] = wj
	}
	if screen != nil {
		sj := model.JSON{}
		for k, v := range screen {
			sj[k] = v
		}
		patch["screen_overrides"] = sj
	}
	if len(patch) == 0 {
		return job, nil
	}
	if err := s.repos.Job().UpdateOverrides(tenantID, jobID, patch); err != nil {
		return nil, err
	}
	logger.L(ctx).Info().Str("job_id", jobID).Int("weights", len(weights)).
		Int("screen", len(screen)).Msg("job overrides updated")
	return s.repos.Job().FindByID(tenantID, jobID)
}

func (s *JobService) List(tenantID string) ([]model.Job, error) {
	return s.repos.Job().List(tenantID)
}

func (s *JobService) Delete(ctx context.Context, tenantID, id string) error {
	return s.repos.Job().Delete(tenantID, id)
}

func toAnySlice(items []string) []interface{} {
	out := make([]interface{}, 0, len(items))
	for _, it := range items {
		out = append(out, it)
	}
	return out
}
