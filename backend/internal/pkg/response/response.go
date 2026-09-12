// Package response 统一 HTTP 响应包装与错误出口。
package response

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/logger"
)

// Body 统一响应体。
type Body struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
	TraceID string      `json:"trace_id,omitempty"`
}

func OK(c *gin.Context, data interface{}) {
	c.JSON(http.StatusOK, Body{Code: 200, Message: "success", Data: data, TraceID: c.GetString("trace_id")})
}

// Created 201 响应。
func Created(c *gin.Context, data interface{}) {
	c.JSON(http.StatusCreated, Body{Code: 201, Message: "created", Data: data, TraceID: c.GetString("trace_id")})
}

// Accepted 202 异步任务受理。
func Accepted(c *gin.Context, data interface{}) {
	c.JSON(http.StatusAccepted, Body{Code: 202, Message: "accepted", Data: data, TraceID: c.GetString("trace_id")})
}

// Fail 统一错误出口：AppError 按其状态码，未知错误 500 并记录堆栈。
func Fail(c *gin.Context, err error) {
	ae := apperror.From(err)
	log := logger.From(c.Request.Context())
	if ae.Code >= 50000 {
		log.Error().Err(err).Int("code", ae.Code).Msg("request failed")
	} else {
		log.Warn().Err(err).Int("code", ae.Code).Msg("request rejected")
	}
	if c.Writer.Written() {
		return
	}
	c.AbortWithStatusJSON(ae.HTTPStatus, Body{Code: ae.Code, Message: ae.Message, TraceID: c.GetString("trace_id")})
}

// AbortErr 中间件内中断（如鉴权/限流失败）。
func AbortErr(c *gin.Context, err error) {
	Fail(c, err)
	if !c.IsAborted() {
		c.Abort()
	}
}
