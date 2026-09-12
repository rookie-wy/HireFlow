// Package handler HTTP 处理层。
package handler

import (
	"github.com/gin-gonic/gin"

	"github.com/ai-recruitment/backend/internal/middleware"
	"github.com/ai-recruitment/backend/internal/pkg/response"
	"github.com/ai-recruitment/backend/internal/service"
)

// AuthHandler 认证接口。
type AuthHandler struct{ auth *service.AuthService }

func NewAuthHandler(auth *service.AuthService) *AuthHandler { return &AuthHandler{auth: auth} }

type RegisterRequest struct {
	Username string `json:"username" binding:"required,min=3,max=64"`
	Password string `json:"password" binding:"required,min=8,max=128"`
	TenantID string `json:"tenant_id" binding:"required,min=1,max=64"`
	Role     string `json:"role"`
}

func (h *AuthHandler) Register(c *gin.Context) {
	var req RegisterRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Fail(c, err)
		return
	}
	result, err := h.auth.Register(service.RegisterInput{
		Username: req.Username, Password: req.Password, TenantID: req.TenantID, Role: req.Role,
	})
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.Created(c, result)
}

type LoginRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
	TenantID string `json:"tenant_id" binding:"required"`
}

func (h *AuthHandler) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Fail(c, err)
		return
	}
	result, err := h.auth.Login(req.Username, req.Password, req.TenantID)
	if err != nil {
		response.Fail(c, err)
		return
	}
	response.OK(c, result)
}

// Me 当前用户信息。
func (h *AuthHandler) Me(c *gin.Context) {
	response.OK(c, gin.H{
		"user_id":   middleware.UserID(c),
		"tenant_id": middleware.TenantID(c),
		"role":      c.GetString(middleware.CtxRole),
	})
}
