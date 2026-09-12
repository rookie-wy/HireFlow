package middleware

import (
	"context"
	"fmt"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"

	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/logger"
	"github.com/ai-recruitment/backend/internal/pkg/response"
)

// slidingWindowZSETKey 限流键前缀。
const rlKeyPrefix = "rl:"

// RateLimit Redis 滑动窗口限流。
// key 维度自定义（如 ip、user），limit 为每分钟最大请求数。
// Redis 不可用时降级放行并告警（可用性优先）。
func RateLimit(rdb *redis.Client, scope string, limitPerMin int) gin.HandlerFunc {
	return func(c *gin.Context) {
		if rdb == nil {
			c.Next()
			return
		}
		ctx, cancel := context.WithTimeout(c.Request.Context(), 300*time.Millisecond)
		defer cancel()

		now := time.Now()
		windowStart := now.Add(-time.Minute)
		key := fmt.Sprintf("%s%s:%s", rlKeyPrefix, scope, clientKey(c))

		pipe := rdb.TxPipeline()
		pipe.ZRemRangeByScore(ctx, key, "0", fmt.Sprintf("%d", windowStart.UnixMilli()))
		countCmd := pipe.ZCard(ctx, key)
		pipe.Expire(ctx, key, 2*time.Minute)
		if _, err := pipe.Exec(ctx); err != nil && err != redis.Nil {
			logger.L(c.Request.Context()).Warn().Err(err).Str("scope", scope).Msg("rate limit backend unavailable, allowing request")
			c.Next()
			return
		}
		if int(countCmd.Val()) >= limitPerMin {
			response.AbortErr(c, apperror.ErrTooManyRequests)
			return
		}
		rdb.ZAdd(ctx, key, redis.Z{Score: float64(now.UnixMilli()), Member: fmt.Sprintf("%d", now.UnixNano())})
		c.Next()
	}
}

// clientKey 限流维度：登录/上传/筛选统一按 IP，已登录请求叠加租户+用户。
func clientKey(c *gin.Context) string {
	if uid := UserID(c); uid != "" {
		return TenantID(c) + ":" + uid
	}
	return c.ClientIP()
}
