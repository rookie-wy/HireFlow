package handler

import (
	"io"
	"mime/multipart"

	"github.com/ai-recruitment/backend/internal/pkg/apperror"
)

// readAllLimit 读取文件内容并限制上传体积。
func readAllLimit(f multipart.File, max int64) ([]byte, error) {
	content, err := io.ReadAll(io.LimitReader(f, max+1))
	if err != nil {
		return nil, apperror.ErrUploadInvalid.WithCause(err)
	}
	return content, nil
}
