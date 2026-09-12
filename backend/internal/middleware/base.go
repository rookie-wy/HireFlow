// Package middleware Gin 中间件：链路追踪、JWT 认证、RBAC、限流、恢复。
package middleware

import (
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"

	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/logger"
	"github.com/ai-recruitment/backend/internal/pkg/metrics"
	"github.com/ai-recruitment/backend/internal/pkg/response"
)

// Trace 注入/透传 X-Trace-Id 并写入日志 context。
func Trace() gin.HandlerFunc {
	return func(c *gin.Context) {
		traceID := c.GetHeader("X-Trace-Id")
		if traceID == "" {
			traceID = uuid.NewString()
		}
		c.Set("trace_id", traceID)
		c.Header("X-Trace-Id", traceID)
		ctx := logger.WithTraceID(c.Request.Context(), traceID)
		c.Request = c.Request.WithContext(ctx)
		c.Next()
	}
}

// RequestLogger 请求访问日志 + HTTP 指标（O6）。
// 指标标签用「路由模板」而非实际路径，避免 /screen/tasks/<uuid> 造成标签爆炸。
func RequestLogger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		elapsed := time.Since(start).Seconds()
		logger.L(c.Request.Context()).Info().
			Str("method", c.Request.Method).
			Str("path", c.Request.URL.Path).
			Int("status", c.Writer.Status()).
			Int64("cost_ms", time.Since(start).Milliseconds()).
			Msg("http access")

		route := c.FullPath()
		if route == "" {
			route = "unmatched"
		}
		labels := map[string]string{
			"method": c.Request.Method,
			"route":  route,
			"status": strconv.Itoa(c.Writer.Status()),
		}
		metrics.Inc("http_requests", 1, labels)
		metrics.Observe("http_request_seconds", elapsed, map[string]string{
			"method": c.Request.Method,
			"route":  route,
		})
	}
}

// Recovery panic 恢复并返回统一 500。
func Recovery() gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				logger.L(c.Request.Context()).Error().Interface("panic", r).Msg("panic recovered")
				response.AbortErr(c, apperror.New(50000, "服务内部错误", 500))
			}
		}()
		c.Next()
	}
}
