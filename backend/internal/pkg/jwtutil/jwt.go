// Package jwtutil JWT 签发与校验（HS256）。
package jwtutil

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/ai-recruitment/backend/internal/pkg/apperror"
)

// Claims 携带租户与角色，多租户与 RBAC 的依据。
type Claims struct {
	UserID   string `json:"uid"`
	TenantID string `json:"tid"`
	Role     string `json:"role"`
	jwt.RegisteredClaims
}

type Manager struct {
	secret []byte
	issuer string
	expire time.Duration
}

func NewManager(secret, issuer string, expireMinutes int) *Manager {
	return &Manager{secret: []byte(secret), issuer: issuer, expire: time.Duration(expireMinutes) * time.Minute}
}

func (m *Manager) CreateToken(userID, tenantID, role string) (string, error) {
	now := time.Now()
	claims := Claims{
		UserID: userID, TenantID: tenantID, Role: role,
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer:    m.issuer,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(m.expire)),
		},
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(m.secret)
}

func (m *Manager) Parse(tokenStr string) (*Claims, error) {
	token, err := jwt.ParseWithClaims(tokenStr, &Claims{}, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return m.secret, nil
	})
	if err != nil || !token.Valid {
		return nil, apperror.ErrUnauthorized.WithCause(err)
	}
	claims, ok := token.Claims.(*Claims)
	if !ok || claims.UserID == "" || claims.TenantID == "" {
		return nil, apperror.ErrUnauthorized
	}
	return claims, nil
}
