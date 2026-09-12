// Package service 业务逻辑层。
package service

import (
	"github.com/google/uuid"

	"github.com/ai-recruitment/backend/internal/model"
	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/jwtutil"
	"github.com/ai-recruitment/backend/internal/pkg/password"
	"github.com/ai-recruitment/backend/internal/repository"
)

// AuthService 注册 / 登录。
type AuthService struct {
	repos *repository.Repos
	jwt   *jwtutil.Manager
}

func NewAuthService(repos *repository.Repos, jm *jwtutil.Manager) *AuthService {
	return &AuthService{repos: repos, jwt: jm}
}

type RegisterInput struct {
	Username string
	Password string
	TenantID string
	Role     string
}

var validRoles = map[string]bool{"hr": true, "manager": true, "admin": true}

func (s *AuthService) Register(in RegisterInput) (map[string]string, error) {
	if len(in.Username) < 3 || len(in.Username) > 64 {
		return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000, "用户名长度需 3-64 字符", 400))
	}
	if len(in.Password) < 8 || len(in.Password) > 128 {
		return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000, "密码长度需 8-128 字符", 400))
	}
	if in.TenantID == "" {
		return nil, apperror.ErrBadRequest.WithCause(apperror.New(40000, "tenant_id 必填", 400))
	}
	if !validRoles[in.Role] {
		in.Role = "hr"
	}
	exists, err := s.repos.User().ExistsByUsername(in.TenantID, in.Username)
	if err != nil {
		return nil, apperror.ErrDatabase.WithCause(err)
	}
	if exists {
		return nil, apperror.ErrConflict
	}
	hash, err := password.Hash(in.Password)
	if err != nil {
		return nil, apperror.New(50000, "密码处理失败", 500).WithCause(err)
	}
	user := &model.User{ID: uuid.NewString(), TenantID: in.TenantID, Username: in.Username, PasswordHash: hash, Role: in.Role}
	if err := s.repos.User().Create(user); err != nil {
		return nil, err
	}
	// 注册即登录：直接签发令牌，返回结构与 Login 完全一致（前端注册后无需再调一次登录）
	return s.issueToken(user)
}

func (s *AuthService) Login(username, pass, tenantID string) (map[string]string, error) {
	user, err := s.repos.User().FindByUsername(tenantID, username)
	if err != nil {
		return nil, err
	}
	if !password.Verify(user.PasswordHash, pass) {
		return nil, apperror.ErrInvalidCredentials
	}
	return s.issueToken(user)
}

// issueToken 统一令牌签发出口，保证 Register/Login 返回契约一致。
func (s *AuthService) issueToken(user *model.User) (map[string]string, error) {
	token, err := s.jwt.CreateToken(user.ID, user.TenantID, user.Role)
	if err != nil {
		return nil, apperror.New(50000, "令牌签发失败", 500).WithCause(err)
	}
	return map[string]string{
		"access_token": token,
		"token_type":   "Bearer",
		"user_id":      user.ID,
		"tenant_id":    user.TenantID,
		"role":         user.Role,
	}, nil
}
