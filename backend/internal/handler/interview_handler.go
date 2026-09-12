package handler

import (
	"github.com/gin-gonic/gin"

	"github.com/ai-recruitment/backend/internal/agenttypes"
	"github.com/ai-recruitment/backend/internal/middleware"
	"github.com/ai-recruitment/backend/internal/pkg/response"
	"github.com/ai-recruitment/backend/internal/service"
)

// InterviewHandler 面试调度接口。
type InterviewHandler struct{ interviews *service.InterviewService }

func NewInterviewHandler(is *service.InterviewService) *InterviewHandler {
	return &InterviewHandler{interviews: is}
}

type DraftRequest struct {
	JobID         string   `json:"job_id" binding:"required"`
	CandidateID   string   `json:"candidate_id" binding:"required"`
	ProposedTimes []string `json:"proposed_times" binding:"required,min=1,max=10"`
}

func (h *InterviewHandler) Draft(c *gin.Context) {
	var req DraftRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Fail(c, err)
		return
	}
	draft, err := h.interviews.Draft(c.Request.Context(), middleware.TenantID(c), req.JobID, req.CandidateID, req.ProposedTimes)
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, draft)
}

type SendRequest struct {
	JobID        string                     `json:"job_id" binding:"required"`
	CandidateID  string                     `json:"candidate_id" binding:"required"`
	Draft        agenttypes.InterviewDraft  `json:"draft" binding:"required"`
	SelectedTime string                     `json:"selected_time"`
}

func (h *InterviewHandler) Send(c *gin.Context) {
	var req SendRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Fail(c, err)
		return
	}
	result, err := h.interviews.Send(
		c.Request.Context(), middleware.TenantID(c), middleware.UserID(c),
		req.JobID, req.CandidateID, req.Draft, req.SelectedTime,
	)
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, result)
}

type ReplyIntentRequest struct {
	ReplyBody string `json:"reply_body" binding:"required,max=5000"`
}

func (h *InterviewHandler) ReplyIntent(c *gin.Context) {
	var req ReplyIntentRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Fail(c, err)
		return
	}
	intent, err := h.interviews.ReplyIntent(c.Request.Context(), req.ReplyBody)
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, intent)
}
