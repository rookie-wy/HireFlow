package handler

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
	"gorm.io/gorm"

)

// HealthHandler liveness / readiness。
type HealthHandler struct {
	db       *gorm.DB
	rdb      *redis.Client
	agentURL string
}

func NewHealthHandler(db *gorm.DB, rdb *redis.Client, agentURL string) *HealthHandler {
	return &HealthHandler{db: db, rdb: rdb, agentURL: agentURL}
}

// Liveness 进程存活即 OK。
func (h *HealthHandler) Liveness(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

// Readiness 依赖检查：MySQL / Redis / agent 服务。
func (h *HealthHandler) Readiness(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
	defer cancel()

	checks := gin.H{"mysql": check("mysql", h.db != nil && pingMySQL(ctx, h.db))}
	if h.rdb != nil {
		checks["redis"] = check("redis", h.rdb.Ping(ctx).Err() == nil)
	}
	checks["agent"] = check("agent", pingAgent(ctx, h.agentURL))

	allOK := true
	for _, v := range checks {
		if m := v.(gin.H); m["status"] != "ok" {
			allOK = false
		}
	}
	status := "ok"
	code := http.StatusOK
	if !allOK {
		status = "degraded"
		code = http.StatusServiceUnavailable
	}
	c.JSON(code, gin.H{"status": status, "checks": checks})
}

func check(name string, ok bool) gin.H {
	s := "ok"
	if !ok {
		s = "fail"
	}
	return gin.H{"status": s}
}

func pingMySQL(ctx context.Context, db *gorm.DB) bool {
	sqlDB, err := db.DB()
	if err != nil {
		return false
	}
	return sqlDB.PingContext(ctx) == nil
}

func pingAgent(ctx context.Context, baseURL string) bool {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, baseURL+"/healthz", nil)
	if err != nil {
		return false
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}
