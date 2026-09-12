// Package redisclient Redis 连接与分布式锁。
package redisclient

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

// Connect 解析 redis:// URL 并建立客户端。
func Connect(url string) (*redis.Client, error) {
	opts, err := redis.ParseURL(url)
	if err != nil {
		return nil, fmt.Errorf("parse redis url: %w", err)
	}
	opts.DialTimeout = 3 * time.Second
	opts.ReadTimeout = 2 * time.Second
	client := redis.NewClient(opts)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis ping: %w", err)
	}
	return client, nil
}

// Lock 分布式锁（SET NX EX + Lua 原子释放，防误删）。
type Lock struct {
	client *redis.Client
	key    string
	token  string
	ttl    time.Duration
}

var releaseScript = redis.NewScript(`
if redis.call("GET", KEYS[1]) == ARGV[1] then
	return redis.call("DEL", KEYS[1])
else
	return 0
end
`)

// Acquire 获取锁；失败返回 ErrLockHeld。
func Acquire(ctx context.Context, client *redis.Client, key string, ttl time.Duration) (*Lock, error) {
	token := uuid.NewString()
	ok, err := client.SetNX(ctx, "lock:"+key, token, ttl).Result()
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, ErrLockHeld
	}
	return &Lock{client: client, key: "lock:" + key, token: token, ttl: ttl}, nil
}

var ErrLockHeld = errors.New("lock already held")

func (l *Lock) Release(ctx context.Context) error {
	return releaseScript.Run(ctx, l.client, []string{l.key}, l.token).Err()
}

// IdempotentGuard 幂等保护：NX+EX 占位成功才算首次请求。
type IdempotentGuard struct {
	client *redis.Client
	key    string
	token  string
}

// NewIdempotent 占位成功返回 guard；重复请求返回 ErrLockHeld。
func NewIdempotent(ctx context.Context, client *redis.Client, key string, ttl time.Duration) (*IdempotentGuard, error) {
	token := uuid.NewString()
	ok, err := client.SetNX(ctx, "idem:"+key, token, ttl).Result()
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, ErrLockHeld
	}
	return &IdempotentGuard{client: client, key: "idem:" + key, token: token}, nil
}

// Release 完成后释放（含失败场景主动回滚）。
func (g *IdempotentGuard) Release(ctx context.Context) {
	releaseScript.Run(ctx, g.client, []string{g.key}, g.token)
}
