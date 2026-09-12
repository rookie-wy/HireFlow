// Package logger 提供 zerolog 结构化日志，trace_id 从 context 注入。
package logger

import (
	"context"
	"os"
	"time"

	"github.com/rs/zerolog"
)

type ctxKey string

const traceIDKey ctxKey = "trace_id"

// TraceIDFromContext 取当前链路 trace_id。
func TraceIDFromContext(ctx context.Context) string {
	if v, ok := ctx.Value(traceIDKey).(string); ok {
		return v
	}
	return ""
}

// WithTraceID 将 trace_id 写入 context。
func WithTraceID(ctx context.Context, traceID string) context.Context {
	return context.WithValue(ctx, traceIDKey, traceID)
}

// Init 初始化全局日志风格：JSON（生产）/ console（开发）。
func Init(prod bool) {
	zerolog.SetGlobalLevel(zerolog.InfoLevel)
	zerolog.TimestampFunc = time.Now
	if !prod {
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
	}
}

// From 返回带 trace_id 的 logger。生产为 JSON，开发为 console。
func From(ctx context.Context) zerolog.Logger {
	var l zerolog.Logger
	if isProd() {
		l = zerolog.New(os.Stdout).With().Timestamp().Logger()
	} else {
		l = zerolog.New(zerolog.ConsoleWriter{Out: os.Stdout, TimeFormat: time.RFC3339}).With().Timestamp().Logger()
	}
	if tid := TraceIDFromContext(ctx); tid != "" {
		return l.With().Str("trace_id", tid).Logger()
	}
	return l
}

// Global 无 context 场景（启动/关闭阶段）。
func Global() zerolog.Logger {
	return From(context.Background())
}

// L 返回可链式调用的 logger 指针（zerolog 事件方法为指针接收者）。
func L(ctx context.Context) *zerolog.Logger {
	l := From(ctx)
	return &l
}

// LG 全局 logger 指针。
func LG() *zerolog.Logger {
	l := Global()
	return &l
}

func isProd() bool { return os.Getenv("APP_ENV") == "production" }
