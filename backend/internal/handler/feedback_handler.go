package handler

import (
	"github.com/gin-gonic/gin"

	"github.com/ai-recruitment/backend/internal/middleware"
	"github.com/ai-recruitment/backend/internal/pkg/response"
	"github.com/ai-recruitment/backend/internal/service"
)

// FeedbackHandler 反馈接口。
type FeedbackHandler struct{ feedback *service.FeedbackService }

func NewFeedbackHandler(fb *service.FeedbackService) *FeedbackHandler {
	return &FeedbackHandler{feedback: fb}
}

type FeedbackRequest struct {
	CandidateID string `json:"candidate_id" binding:"required"`
	JobID       string `json:"job_id" binding:"required"`
	Feedback    string `json:"feedback" binding:"required"`
	SessionID   string `json:"session_id"`
}

func (h *FeedbackHandler) Submit(c *gin.Context) {
	var req FeedbackRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Fail(c, err)
		return
	}
	if err := h.feedback.Process(
		c.Request.Context(),
		middleware.TenantID(c), middleware.UserID(c),
		req.CandidateID, req.JobID, req.Feedback, req.SessionID,
	); err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, gin.H{"status": "ok"})
}
