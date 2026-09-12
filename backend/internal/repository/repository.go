// Package repository 数据访问层。所有查询强制 tenant_id 隔离。
package repository

import (
	"errors"

	"gorm.io/gorm"

	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
)

// Repos 仓储集合。
type Repos struct {
	db *gorm.DB
}

func NewRepos(db *gorm.DB) *Repos { return &Repos{db: db} }

// UserRepo 用户仓储。
type UserRepo struct{ db *gorm.DB }

func (r *Repos) User() *UserRepo { return &UserRepo{r.db} }

func (r *UserRepo) Create(user *model.User) error {
	if err := r.db.Create(user).Error; err != nil {
		return apperror.ErrConflict.WithCause(err)
	}
	return nil
}

func (r *UserRepo) FindByUsername(tenantID, username string) (*model.User, error) {
	var u model.User
	err := r.db.Where("tenant_id = ? AND username = ?", tenantID, username).First(&u).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, apperror.ErrInvalidCredentials
	}
	if err != nil {
		return nil, apperror.ErrDatabase.WithCause(err)
	}
	return &u, nil
}

func (r *UserRepo) ExistsByUsername(tenantID, username string) (bool, error) {
	var count int64
	err := r.db.Model(&model.User{}).Where("tenant_id = ? AND username = ?", tenantID, username).Count(&count).Error
	return count > 0, err
}

func (r *UserRepo) FindByID(tenantID, userID string) (*model.User, error) {
	var u model.User
	err := r.db.Where("tenant_id = ? AND id = ?", tenantID, userID).First(&u).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, apperror.ErrNotFound
	}
	return &u, err
}

func (r *UserRepo) List(tenantID string) ([]model.User, error) {
	var users []model.User
	err := r.db.Where("tenant_id = ?", tenantID).Order("created_at DESC").Find(&users).Error
	return users, err
}
