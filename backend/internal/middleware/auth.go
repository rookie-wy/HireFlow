package middleware

import (
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/jwtutil"
	"github.com/ai-recruitment/backend/internal/pkg/response"
)

// Context 键名。
const (
	CtxUserID   = "user_id"
	CtxTenantID = "tenant_id"
	CtxRole     = "role"
)

// Auth JWT 认证：解析 Bearer Token，注入用户身份到 context。
func Auth(jm *jwtutil.Manager) gin.HandlerFunc {
	return func(c *gin.Context) {
		header := c.GetHeader("Authorization")
		if !strings.HasPrefix(header, "Bearer ") {
			response.AbortErr(c, apperror.ErrUnauthorized)
			return
		}
		claims, err := jm.Parse(strings.TrimPrefix(header, "Bearer "))
		if err != nil {
			response.AbortErr(c, err)
			return
		}
		c.Set(CtxUserID, claims.UserID)
		c.Set(CtxTenantID, claims.TenantID)
		c.Set(CtxRole, claims.Role)
		c.Next()
	}
}

// RequireRole RBAC：当前角色不在允许列表内则 403。
func RequireRole(roles ...string) gin.HandlerFunc {
	allowed := make(map[string]struct{}, len(roles))
	for _, r := range roles {
		allowed[r] = struct{}{}
	}
	return func(c *gin.Context) {
		role := c.GetString(CtxRole)
		if _, ok := allowed[role]; !ok {
			response.AbortErr(c, apperror.ErrForbidden)
			return
		}
		c.Next()
	}
}

// TenantID 从 context 取当前租户（repository 层隔离依据）。
func TenantID(c *gin.Context) string { return c.GetString(CtxTenantID) }

// UserID 从 context 取当前用户。
func UserID(c *gin.Context) string { return c.GetString(CtxUserID) }
