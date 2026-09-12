// Package apperror 定义统一业务错误码体系。
// 错误码段：400xx 业务 / 401xx 认证 / 403xx 权限 / 429xx 限流 / 500xx 服务端。
package apperror

import (
	"errors"
	"fmt"
	"net/http"
)

type AppError struct {
	Code       int    // 业务错误码
	Message    string // 用户可读信息
	HTTPStatus int
	cause      error
}

func (e *AppError) Error() string {
	if e.cause != nil {
		return fmt.Sprintf("[%d] %s: %v", e.Code, e.Message, e.cause)
	}
	return fmt.Sprintf("[%d] %s", e.Code, e.Message)
}

func (e *AppError) Unwrap() error { return e.cause }

// WithCause 包装底层错误用于日志排查。
func (e *AppError) WithCause(err error) *AppError {
	e.cause = err
	return e
}

func New(code int, message string, httpStatus int) *AppError {
	return &AppError{Code: code, Message: message, HTTPStatus: httpStatus}
}

// 预定义错误（业务层直接引用或 WithCause 包装）。
var (
	ErrBadRequest      = New(40000, "请求参数不合法", http.StatusBadRequest)
	ErrNotFound        = New(40400, "资源不存在", http.StatusNotFound)
	ErrConflict        = New(40900, "资源已存在", http.StatusConflict)
	ErrUnauthorized    = New(40100, "未认证或凭证失效", http.StatusUnauthorized)
	ErrInvalidCredentials = New(40101, "用户名或密码错误", http.StatusUnauthorized)
	ErrForbidden       = New(40300, "无权限执行该操作", http.StatusForbidden)
	ErrTooManyRequests = New(42900, "请求过于频繁，请稍后再试", http.StatusTooManyRequests)
	ErrDatabase        = New(50001, "数据库操作失败", http.StatusInternalServerError)
	ErrUpstream        = New(50002, "下游服务不可用", http.StatusBadGateway)
	ErrLLM             = New(50003, "AI 能力调用失败", http.StatusBadGateway)
	ErrTaskNotFound    = New(40401, "任务不存在", http.StatusNotFound)
	ErrIdempotent      = New(40901, "重复请求，操作已在处理中", http.StatusConflict)
	ErrUploadInvalid   = New(40001, "文件类型不支持或超出大小限制", http.StatusBadRequest)
)

// From 将任意 error 归一化为 *AppError（未知错误按 500 处理）。
func From(err error) *AppError {
	if err == nil {
		return nil
	}
	var ae *AppError
	if errors.As(err, &ae) {
		return ae
	}
	return New(50000, "服务内部错误", http.StatusInternalServerError).WithCause(err)
}
