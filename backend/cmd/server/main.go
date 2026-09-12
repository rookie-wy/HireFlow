// AI招聘Agent系统 — 业务中台入口。
package main

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ai-recruitment/backend/internal/config"
	"github.com/ai-recruitment/backend/internal/database"
	"github.com/ai-recruitment/backend/internal/pkg/jwtutil"
	"github.com/ai-recruitment/backend/internal/pkg/logger"
	"github.com/ai-recruitment/backend/internal/pkg/redisclient"
	"github.com/ai-recruitment/backend/internal/repository"
	"github.com/ai-recruitment/backend/internal/router"
)

func main() {
	log := logger.Global()
	cfg, err := config.Load()
	if err != nil {
		log.Fatal().Err(err).Msg("load config")
	}
	logger.Init(cfg.IsProd())

	db, err := database.Connect(cfg.DatabaseURL)
	if err != nil {
		log.Fatal().Err(err).Msg("connect mysql")
	}
	if err := database.Migrate(db); err != nil {
		log.Fatal().Err(err).Msg("run migrations")
	}

	rdb, err := redisclient.Connect(cfg.RedisURL)
	if err != nil {
		log.Fatal().Err(err).Msg("connect redis")
	}

	deps := router.Deps{
		Cfg:   cfg,
		DB:    db,
		Redis: rdb,
		Repos: repository.NewRepos(db),
		JWT:   jwtutil.NewManager(cfg.JWTSecret, cfg.JWTIssuer, cfg.JWTExpireMinutes),
	}
	srv := &http.Server{
		Addr:    ":" + cfg.HTTPPort,
		Handler: router.New(deps),
	}

	go func() {
		log.Info().Str("port", cfg.HTTPPort).Msg("backend listening")
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatal().Err(err).Msg("http server")
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Info().Msg("shutting down...")

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Error().Err(err).Msg("forced shutdown")
	}
	_ = rdb.Close()
	log.Info().Msg("bye")
}
