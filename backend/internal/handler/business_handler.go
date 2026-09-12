package handler

import (
	"github.com/gin-gonic/gin"

	"github.com/ai-recruitment/backend/internal/middleware"
	"github.com/ai-recruitment/backend/internal/pkg/response"
	"github.com/ai-recruitment/backend/internal/service"
)

// JobHandler 岗位接口。
type JobHandler struct{ jobs *service.JobService }

func NewJobHandler(jobs *service.JobService) *JobHandler { return &JobHandler{jobs: jobs} }

type CreateJobRequest struct {
	JDText   string `json:"jd_text" binding:"required,max=50000"`
	Language string `json:"language"`
}

func (h *JobHandler) Create(c *gin.Context) {
	var req CreateJobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Fail(c, err)
		return
	}
	result, err := h.jobs.Create(c.Request.Context(), middleware.TenantID(c), req.JDText, req.Language)
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.Created(c, result)
}

// UpdateOverrides 设置岗位级配置（权重 / 检索参数覆盖）。
type UpdateOverridesRequest struct {
	Weights map[string]float64 `json:"weights"`
	Screen  map[string]any     `json:"screen"`
}

func (h *JobHandler) UpdateOverrides(c *gin.Context) {
	var req UpdateOverridesRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Fail(c, err)
		return
	}
	job, err := h.jobs.UpdateOverrides(c.Request.Context(), middleware.TenantID(c),
		c.Param("job_id"), req.Weights, req.Screen)
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, job)
}

func (h *JobHandler) List(c *gin.Context) {
	jobs, err := h.jobs.List(middleware.TenantID(c))
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, jobs)
}

func (h *JobHandler) Delete(c *gin.Context) {
	if err := h.jobs.Delete(c.Request.Context(), middleware.TenantID(c), c.Param("job_id")); err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, nil)
}

// CandidateHandler 候选人接口。
type CandidateHandler struct{ candidates *service.CandidateService }

func NewCandidateHandler(cs *service.CandidateService) *CandidateHandler {
	return &CandidateHandler{candidates: cs}
}

func (h *CandidateHandler) Upload(c *gin.Context) {
	fileHeader, err := c.FormFile("file")
	if err != nil {
		response.Fail(c, err)
		return
	}
	f, err := fileHeader.Open()
	if err != nil {
		response.Fail(c, err)
		return
	}
	defer f.Close()

	content, err := readAllLimit(f, 32<<20)
	if err != nil {
		response.Fail(c, err)
		return
	}
	candidate, profile, err := h.candidates.Upload(c.Request.Context(), middleware.TenantID(c), fileHeader.Filename, content)
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.Created(c, gin.H{"candidate_id": candidate.ID, "profile": profile})
}

func (h *CandidateHandler) List(c *gin.Context) {
	candidates, err := h.candidates.List(middleware.TenantID(c))
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, candidates)
}

func (h *CandidateHandler) Delete(c *gin.Context) {
	if err := h.candidates.Delete(c.Request.Context(), middleware.TenantID(c), c.Param("candidate_id")); err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, nil)
}
