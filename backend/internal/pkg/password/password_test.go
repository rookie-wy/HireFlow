package password_test

import (
	"testing"

	"github.com/ai-recruitment/backend/internal/pkg/password"
)

func TestHashAndVerify(t *testing.T) {
	hash, err := password.Hash("s3cret-password")
	if err != nil {
		t.Fatalf("hash: %v", err)
	}
	if !password.Verify(hash, "s3cret-password") {
		t.Fatal("correct password should verify")
	}
	if password.Verify(hash, "wrong") {
		t.Fatal("wrong password should not verify")
	}
}

func TestHashLongPassword(t *testing.T) {
	long := make([]byte, 100)
	for i := range long {
		long[i] = 'a'
	}
	hash, err := password.Hash(string(long))
	if err != nil {
		t.Fatalf("hash long password: %v", err)
	}
	if !password.Verify(hash, string(long)) {
		t.Fatal("long password should verify")
	}
}
