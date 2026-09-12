// Package database MySQL 连接与版本化迁移（内嵌 SQL，schema_migrations 记录已应用版本）。
package database

import (
	"context"
	"embed"
	"fmt"
	"sort"
	"strings"
	"time"

	"gorm.io/driver/mysql"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"

	"github.com/ai-recruitment/backend/internal/pkg/logger"
)

//go:embed migrations/*.sql
var migrationFS embed.FS

// Connect 建立 GORM 连接。
func Connect(dsn string) (*gorm.DB, error) {
	db, err := gorm.Open(mysql.Open(dsn), &gorm.Config{
		Logger: gormlogger.Default.LogMode(gormlogger.Warn),
		NowFunc: func() time.Time { return time.Now() },
	})
	if err != nil {
		return nil, err
	}
	sqlDB, err := db.DB()
	if err != nil {
		return nil, err
	}
	sqlDB.SetMaxOpenConns(20)
	sqlDB.SetMaxIdleConns(5)
	sqlDB.SetConnMaxLifetime(30 * time.Minute)
	return db, nil
}

// Migrate 按文件名序执行未应用的 *.up.sql。
func Migrate(db *gorm.DB) error {
	if err := db.Exec(`CREATE TABLE IF NOT EXISTS schema_migrations (
		version VARCHAR(64) PRIMARY KEY,
		applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`).Error; err != nil {
		return fmt.Errorf("create schema_migrations: %w", err)
	}

	entries, err := migrationFS.ReadDir("migrations")
	if err != nil {
		return err
	}
	var names []string
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".up.sql") {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)

	for _, name := range names {
		var count int64
		if err := db.Table("schema_migrations").Where("version = ?", name).Count(&count).Error; err != nil {
			return err
		}
		if count > 0 {
			continue
		}
		content, err := migrationFS.ReadFile("migrations/" + name)
		if err != nil {
			return err
		}
		log := logger.LG().Info().Str("migration", name)
		err = db.Transaction(func(tx *gorm.DB) error {
			for _, stmt := range splitStatements(string(content)) {
				if stmt == "" {
					continue
				}
				if err := tx.Exec(stmt).Error; err != nil {
					return fmt.Errorf("statement error: %w", err)
				}
			}
			return tx.Exec("INSERT INTO schema_migrations (version) VALUES (?)", name).Error
		})
		if err != nil {
			return fmt.Errorf("apply %s: %w", name, err)
		}
		log.Msg("migration applied")
	}
	return nil
}

// splitStatements 按 ; 切分 SQL（本迁移不含存储过程，够用）。
func splitStatements(sqlText string) []string {
	raw := strings.Split(sqlText, ";")
	out := make([]string, 0, len(raw))
	for _, s := range raw {
		s = strings.TrimSpace(s)
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}

// Ping 健康检查。
func Ping(ctx context.Context, db *gorm.DB) error {
	sqlDB, err := db.DB()
	if err != nil {
		return err
	}
	return sqlDB.PingContext(ctx)
}
