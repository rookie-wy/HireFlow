// Package config 提供环境变量驱动的集中配置。
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Config 全部运行时配置，均可用环境变量覆盖。
type Config struct {
	AppEnv  string // development | production
	HTTPPort string

	DatabaseURL     string
	RedisURL        string
	AgentBaseURL    string
	AgentInternalKey string

	JWTSecret        string
	JWTIssuer        string
	JWTExpireMinutes int

	CORSOrigins []string

	RateLimitGlobalPerMin int
	RateLimitLoginPerMin  int
	RateLimitUploadPerMin int
	RateLimitScreenPerMin int

	UploadMaxBytes     int64
	AllowedUploadExt   []string

	// 筛选任务
	ScreenWorkerCount  int
	ScreenQueueSize    int
	ScreenTaskTimeoutSec int
	// ScreenBatchSize 每批送粗筛的候选人数（0 用默认页大小）
	ScreenBatchSize int
}

func (c *Config) IsProd() bool { return c.AppEnv == "production" }

// Load 从环境变量读取配置，生产环境对密钥类配置 fail-fast。
// 支持工作目录/可执行文件同目录的 .env（不覆盖已存在的环境变量）。
func Load() (*Config, error) {
	loadDotEnv()
	c := &Config{
		AppEnv:            getEnv("APP_ENV", "development"),
		HTTPPort:          getEnv("HTTP_PORT", "8080"),
		DatabaseURL:       getEnv("DATABASE_URL", "root:password@tcp(localhost:3306)/recruitment?charset=utf8mb4&parseTime=True&loc=Local"),
		RedisURL:          getEnv("REDIS_URL", "redis://localhost:6379/0"),
		AgentBaseURL:      getEnv("AGENT_BASE_URL", "http://localhost:8001"),
		AgentInternalKey:  os.Getenv("AGENT_INTERNAL_KEY"),
		JWTSecret:         os.Getenv("JWT_SECRET_KEY"),
		JWTIssuer:         getEnv("JWT_ISSUER", "ai-recruitment-backend"),
		JWTExpireMinutes:  getEnvInt("JWT_EXPIRE_MINUTES", 60),
		RateLimitGlobalPerMin: getEnvInt("RATE_LIMIT_GLOBAL_PER_MIN", 100),
		RateLimitLoginPerMin:  getEnvInt("RATE_LIMIT_LOGIN_PER_MIN", 10),
		RateLimitUploadPerMin: getEnvInt("RATE_LIMIT_UPLOAD_PER_MIN", 20),
		RateLimitScreenPerMin: getEnvInt("RATE_LIMIT_SCREEN_PER_MIN", 5),
		UploadMaxBytes:      int64(getEnvInt("UPLOAD_MAX_MB", 10)) * 1024 * 1024,
		AllowedUploadExt:    []string{".pdf", ".png", ".jpg", ".jpeg"},
		ScreenWorkerCount:   getEnvInt("SCREEN_WORKER_COUNT", 4),
		ScreenQueueSize:     getEnvInt("SCREEN_QUEUE_SIZE", 64),
		ScreenTaskTimeoutSec: getEnvInt("SCREEN_TASK_TIMEOUT_SEC", 300),
		ScreenBatchSize:      getEnvInt("SCREEN_BATCH_SIZE", 0),
	}
	c.CORSOrigins = strings.Split(getEnv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8501"), ",")

	if c.JWTSecret == "" || c.JWTSecret == "change-me" {
		if c.IsProd() {
			return nil, fmt.Errorf("JWT_SECRET_KEY 必须在 production 环境显式配置")
		}
		c.JWTSecret = "dev-only-secret-change-me"
	}
	if c.AgentInternalKey == "" {
		if c.IsProd() {
			return nil, fmt.Errorf("AGENT_INTERNAL_KEY 必须在 production 环境显式配置")
		}
		c.AgentInternalKey = "dev-internal-key"
	}
	return c, nil
}

func getEnv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getEnvInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

// loadDotEnv 读取 .env（KEY=VALUE），已存在的环境变量优先。
func loadDotEnv() {
	for _, path := range []string{".env", "backend/.env"} {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			k, v, ok := strings.Cut(line, "=")
			if !ok {
				continue
			}
			k = strings.TrimSpace(k)
			v = strings.Trim(strings.TrimSpace(v), `"'`)
			if os.Getenv(k) == "" {
				_ = os.Setenv(k, v)
			}
		}
		break
	}
}
