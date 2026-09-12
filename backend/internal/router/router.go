// Package router 路由装配。
package router

import (
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
	"gorm.io/gorm"

	"github.com/ai-recruitment/backend/internal/config"
	"github.com/ai-recruitment/backend/internal/handler"
	"github.com/ai-recruitment/backend/internal/middleware"
	"github.com/ai-recruitment/backend/internal/pkg/agentclient"
	"github.com/ai-recruitment/backend/internal/pkg/jwtutil"
	"github.com/ai-recruitment/backend/internal/pkg/logger"
	"github.com/ai-recruitment/backend/internal/repository"
	"github.com/ai-recruitment/backend/internal/service"
)

// Deps 路由依赖容器。
type Deps struct {
	Cfg   *config.Config
	DB    *gorm.DB
	Redis *redis.Client
	Repos *repository.Repos
	JWT   *jwtutil.Manager
}

func New(d Deps) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	if !d.Cfg.IsProd() {
		gin.SetMode(gin.DebugMode)
	}

	r := gin.New()
	r.Use(middleware.Recovery(), middleware.Trace(), middleware.RequestLogger())
	r.Use(cors(d.Cfg.CORSOrigins))

	healthH := handler.NewHealthHandler(d.DB, d.Redis, d.Cfg.AgentBaseURL)
	r.GET("/healthz", healthH.Liveness)
	r.GET("/readyz", healthH.Readiness)

	// 指标端点（O6）：Prometheus 文本格式；与 agent 的 /healthz/metrics 对称
	metricsH := handler.NewMetricsHandler(d.DB, d.Redis)
	r.GET("/metrics", metricsH.Handler)

	authSvc := service.NewAuthService(d.Repos, d.JWT)
	authH := handler.NewAuthHandler(authSvc)
	loginLimiter := middleware.RateLimit(d.Redis, "login", d.Cfg.RateLimitLoginPerMin)

	v1 := r.Group("/api/v1")
	{
		v1.POST("/auth/register", loginLimiter, authH.Register)
		v1.POST("/auth/login", loginLimiter, authH.Login)

		authed := v1.Group("", middleware.Auth(d.JWT))
		authed.Use(middleware.RateLimit(d.Redis, "global", d.Cfg.RateLimitGlobalPerMin))
		authed.GET("/auth/me", authH.Me)

		// 业务模块（Phase 2+ 持续挂载）
		hrRoles := []string{"hr", "manager", "admin"}
		mgrRoles := []string{"manager", "admin"}

		// agent HTTP 超时取「任务超时 + 30s 余量」：否则任务超时到点时 NDJSON 流不会被打断，
		// 表现为「任务超时配置无效、任务总是跑到底」（踩过一次）
		agentHTTPTimeout := time.Duration(d.Cfg.ScreenTaskTimeoutSec)*time.Second + 30*time.Second
		agentClient := agentclient.New(d.Cfg.AgentBaseURL, d.Cfg.AgentInternalKey, agentHTTPTimeout)
		jobSvc := service.NewJobService(d.Repos, agentClient)
		candSvc := service.NewCandidateService(d.Repos, agentClient, d.Cfg.UploadMaxBytes, d.Cfg.AllowedUploadExt)

		screenTimeout := time.Duration(d.Cfg.ScreenTaskTimeoutSec) * time.Second
		screenSvc := service.NewScreeningService(d.Repos, agentClient, d.Redis, d.DB, screenTimeout, d.Cfg.ScreenQueueSize, d.Cfg.ScreenBatchSize)
		logger.LG().Info().Int("batch_size", d.Cfg.ScreenBatchSize).Int("timeout_sec", d.Cfg.ScreenTaskTimeoutSec).
			Int("workers", d.Cfg.ScreenWorkerCount).Msg("screening config")
		screenSvc.Start(d.Cfg.ScreenWorkerCount)
		feedbackSvc := service.NewFeedbackService(d.Repos, d.Redis)

		jobH := handler.NewJobHandler(jobSvc)
		candH := handler.NewCandidateHandler(candSvc)
		screenH := handler.NewScreenHandler(screenSvc, feedbackSvc, d.Repos, d.Redis)
		feedbackH := handler.NewFeedbackHandler(feedbackSvc)

		jobs := authed.Group("/jobs", middleware.RequireRole(hrRoles...))
		{
			jobs.POST("", middleware.RateLimit(d.Redis, "job_create", 30), jobH.Create)
			jobs.GET("", jobH.List)
			// 岗位级配置（O7）：权重与检索参数覆盖，仅 manager+ 可改
			jobs.PUT("/:job_id/overrides", middleware.RequireRole(mgrRoles...), jobH.UpdateOverrides)
			jobs.DELETE("/:job_id", middleware.RequireRole(mgrRoles...), jobH.Delete)
		}

		candidates := authed.Group("/candidates", middleware.RequireRole(hrRoles...))
		{
			candidates.POST("/upload", middleware.RateLimit(d.Redis, "upload", d.Cfg.RateLimitUploadPerMin), candH.Upload)
			candidates.GET("", candH.List)
			candidates.DELETE("/:candidate_id", middleware.RequireRole(mgrRoles...), candH.Delete)
		}

		screen := authed.Group("/screen", middleware.RequireRole(hrRoles...))
		{
			screen.POST("", middleware.RateLimit(d.Redis, "screen", d.Cfg.RateLimitScreenPerMin), screenH.Submit)
			screen.GET("/tasks/:task_id", screenH.TaskStatus)
			screen.GET("/tasks/:task_id/events", screenH.Events)
			// 失败任务续跑：复用已完成候选人结论，只补未完成部分（O5）
			screen.POST("/tasks/:task_id/retry", screenH.Retry)
			screen.GET("/match-results", screenH.MatchResults)
		}

		authed.POST("/feedback", middleware.RequireRole(hrRoles...), feedbackH.Submit)

		interviewSvc := service.NewInterviewService(d.Repos, agentClient, d.Redis)
		interviewH := handler.NewInterviewHandler(interviewSvc)
		interview := authed.Group("/interview", middleware.RequireRole(hrRoles...))
		{
			interview.POST("/draft", interviewH.Draft)
			interview.POST("/send", interviewH.Send)
			interview.POST("/reply-intent", interviewH.ReplyIntent)
		}
	}
	return r
}

// cors 跨域白名单。
func cors(origins []string) gin.HandlerFunc {
	allow := make(map[string]struct{}, len(origins))
	for _, o := range origins {
		allow[strings.TrimSpace(o)] = struct{}{}
	}
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if _, ok := allow[origin]; ok {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Access-Control-Allow-Credentials", "true")
			c.Header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Trace-Id")
			c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		}
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}
