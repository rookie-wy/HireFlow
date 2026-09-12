package handler

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
	"gorm.io/gorm"

	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/metrics"
)

// MetricsHandler 指标端点：Prometheus 文本格式（/metrics）。
// 除进程内计数器/直方图外，注册几个**采集时查库**的 gauge（成本、结果存量、任务存量），
// 避免在写路径上额外查库，同时保证对外暴露的是最新业务口径。
type MetricsHandler struct {
	db  *gorm.DB
	rdb *redis.Client
}

func NewMetricsHandler(db *gorm.DB, rdb *redis.Client) *MetricsHandler {
	h := &MetricsHandler{db: db, rdb: rdb}
	h.registerBusinessGauges()
	return h
}

// registerBusinessGauges 注册业务类 gauge（采集时求值）。
func (h *MetricsHandler) registerBusinessGauges() {
	if h.db == nil {
		return
	}
	metrics.RegisterGaugeFunc("screen_cost_usd", func() float64 {
		var total float64
		if err := h.db.Model(&model.CostRecord{}).Select("COALESCE(SUM(cost),0)").Scan(&total).Error; err != nil {
			return -1
		}
		return total
	}, nil)

	metrics.RegisterGaugeFunc("llm_tokens", func() float64 {
		var total float64
		if err := h.db.Model(&model.CostRecord{}).
			Select("COALESCE(SUM(tokens_prompt + tokens_completion),0)").Scan(&total).Error; err != nil {
			return -1
		}
		return total
	}, map[string]string{"kind": "total"})

	metrics.RegisterGaugeFunc("match_results_stored", func() float64 {
		var n int64
		if err := h.db.Model(&model.MatchResult{}).Count(&n).Error; err != nil {
			return -1
		}
		return float64(n)
	}, nil)

	metrics.RegisterGaugeFunc("candidates_stored", func() float64 {
		var n int64
		if err := h.db.Model(&model.Candidate{}).Count(&n).Error; err != nil {
			return -1
		}
		return float64(n)
	}, nil)

	for _, st := range []string{
		model.TaskStatusPending, model.TaskStatusRunning,
		model.TaskStatusSucceeded, model.TaskStatusFailed,
	} {
		status := st
		metrics.RegisterGaugeFunc("screen_tasks_stored", func() float64 {
			var n int64
			if err := h.db.Model(&model.ScreeningTask{}).Where("status = ?", status).Count(&n).Error; err != nil {
				return -1
			}
			return float64(n)
		}, map[string]string{"status": status})
	}
}

// Handler 输出指标文本。
func (h *MetricsHandler) Handler(c *gin.Context) {
	if h.rdb != nil {
		stats := h.rdb.PoolStats()
		if stats != nil {
			metrics.SetGauge("redis_pool_idle", float64(stats.IdleConns), nil)
			metrics.SetGauge("redis_pool_open", float64(stats.TotalConns), nil)
		}
	}
	if h.db != nil {
		if sqlDB, err := h.db.DB(); err == nil {
			stats := sqlDB.Stats()
			metrics.SetGauge("mysql_pool_open", float64(stats.OpenConnections), nil)
			metrics.SetGauge("mysql_pool_in_use", float64(stats.InUse), nil)
			metrics.SetGauge("mysql_pool_idle", float64(stats.Idle), nil)
		}
	}
	metrics.SetGauge("process_uptime_seconds", time.Since(startedAt).Seconds(), nil)
	c.Header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	c.String(http.StatusOK, metrics.Render())
}

var startedAt = time.Now()
