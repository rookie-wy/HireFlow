package jwtutil_test

import (
	"testing"

	"github.com/ai-recruitment/backend/internal/pkg/jwtutil"
)

func TestCreateAndParseToken(t *testing.T) {
	m := jwtutil.NewManager("test-secret", "test-iss", 60)
	token, err := m.CreateToken("u-123", "t-abc", "hr")
	if err != nil {
		t.Fatalf("create token: %v", err)
	}
	claims, err := m.Parse(token)
	if err != nil {
		t.Fatalf("parse token: %v", err)
	}
	if claims.UserID != "u-123" || claims.TenantID != "t-abc" || claims.Role != "hr" {
		t.Fatalf("claims mismatch: %+v", claims)
	}
}

func TestParseRejectsTamperedToken(t *testing.T) {
	m1 := jwtutil.NewManager("secret-a", "iss", 60)
	m2 := jwtutil.NewManager("secret-b", "iss", 60)
	token, _ := m1.CreateToken("u1", "t1", "admin")
	if _, err := m2.Parse(token); err == nil {
		t.Fatal("expected error for token signed with different secret")
	}
	if _, err := m2.Parse("garbage"); err == nil {
		t.Fatal("expected error for garbage token")
	}
}
