package repository

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ai-recruitment/backend/internal/config"
	"github.com/ai-recruitment/backend/internal/database"
	"github.com/ai-recruitment/backend/internal/model"
	"github.com/google/uuid"
)

// loadDotEnvFromParents go test 的工作目录在包内，config.Load 只找 CWD 下的 .env，
// 这里向上找到 backend/.env 并把变量注入环境（go test 无 t.Setenv 时也可用）。
func loadDotEnvFromParents(t *testing.T) {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		return
	}
	for i := 0; i < 4; i++ {
		path := filepath.Join(dir, ".env")
		data, err := os.ReadFile(path)
		if err == nil {
			for _, line := range strings.Split(string(data), "\n") {
				line = strings.TrimSpace(line)
				if line == "" || strings.HasPrefix(line, "#") {
					continue
				}
				k, v, ok := strings.Cut(line, "=")
				if !ok {
					continue
				}
				k, v = strings.TrimSpace(k), strings.Trim(strings.TrimSpace(v), `"'`)
				if os.Getenv(k) == "" {
					_ = os.Setenv(k, v)
				}
			}
			t.Logf("loaded env from %s", path)
			return
		}
		dir = filepath.Dir(dir)
	}
}

// newTestDB 连接开发库（未配置/不可达时 skip，保证 CI 无依赖也能过）。
func newTestDB(t *testing.T) (*Repos, *config.Config) {
	t.Helper()
	loadDotEnvFromParents(t)
	cfg, err := config.Load()
	if err != nil {
		t.Skipf("config load failed: %v", err)
	}
	db, err := database.Connect(cfg.DatabaseURL)
	if err != nil {
		t.Skipf("dev MySQL unavailable, skip integration test: %v", err)
	}
	if err := database.Migrate(db); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	return NewRepos(db), cfg
}

// TestListPageAndLoadForScreeningBeyond200 验证：候选人加载不再被静默截断到 200 人（O4）。
func TestListPageAndLoadForScreeningBeyond200(t *testing.T) {
	repos, cfg := newTestDB(t)
	_ = cfg

	tenant := "repo_test_" + uuid.NewString()[:8]
	const total = 250

	rows := make([]model.Candidate, 0, total)
	for i := 0; i < total; i++ {
		rows = append(rows, model.Candidate{
			ID:         uuid.NewString(),
			TenantID:   tenant,
			Name:       fmt.Sprintf("候选人%03d", i),
			Email:      fmt.Sprintf("c%03d@test.local", i),
			ResumeText: "Python 后端",
			ProfileHash: fmt.Sprintf("hash%03d", i),
		})
	}
	if err := repos.db.Create(&rows).Error; err != nil {
		t.Fatalf("seed candidates: %v", err)
	}
	defer func() {
		repos.db.Where("tenant_id = ?", tenant).Delete(&model.Candidate{})
	}()

	count, err := repos.Candidate().CountByTenant(tenant)
	if err != nil || count != total {
		t.Fatalf("CountByTenant = %d, err=%v, want %d", count, err, total)
	}

	// 分页：3 页取满 250（200 + 50）
	seen := map[string]bool{}
	for offset := 0; offset < total; offset += 200 {
		page, err := repos.Candidate().ListPage(tenant, offset, 200)
		if err != nil {
			t.Fatalf("ListPage(offset=%d): %v", offset, err)
		}
		for _, c := range page {
			if seen[c.ID] {
				t.Fatalf("分页出现重复候选人 %s", c.ID)
			}
			seen[c.ID] = true
		}
	}
	if len(seen) != total {
		t.Fatalf("分页共取到 %d 人，期望 %d（说明翻页漏人）", len(seen), total)
	}

	// LoadForScreening 传入 >200 时必须取满，而不是截断到 200
	all, err := repos.Candidate().LoadForScreening(tenant, 300)
	if err != nil {
		t.Fatalf("LoadForScreening: %v", err)
	}
	if len(all) != total {
		t.Fatalf("LoadForScreening(300) 返回 %d 人，期望 %d（仍是旧的 200 硬顶？）", len(all), total)
	}

	// 默认行为不变：limit<=0 时返回一页
	onePage, err := repos.Candidate().LoadForScreening(tenant, 0)
	if err != nil {
		t.Fatalf("LoadForScreening(0): %v", err)
	}
	if len(onePage) != DefaultScreeningPageSize {
		t.Fatalf("LoadForScreening(0) 返回 %d 人，期望一页 %d 人", len(onePage), DefaultScreeningPageSize)
	}
}
