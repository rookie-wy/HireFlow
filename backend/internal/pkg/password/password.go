// Package password 密码哈希（bcrypt）。
package password

import "golang.org/x/crypto/bcrypt"

// Hash bcrypt 加密（72 字节截断保护）。
func Hash(plain string) (string, error) {
	if len(plain) > 72 {
		plain = plain[:72]
	}
	b, err := bcrypt.GenerateFromPassword([]byte(plain), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

// Verify 校验密码，任何异常均视为不匹配。
func Verify(hash, plain string) bool {
	if len(plain) > 72 {
		plain = plain[:72]
	}
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(plain)) == nil
}
