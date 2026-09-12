// Package agentclient backend → agent(Python) 服务的 HTTP 客户端。
// 统一注入 X-Internal-Key 与 X-Trace-Id；统一错误映射。
package agentclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"time"

	"github.com/ai-recruitment/backend/internal/pkg/apperror"
	"github.com/ai-recruitment/backend/internal/pkg/logger"
)

// Client agent 服务客户端。
type Client struct {
	baseURL     string
	internalKey string
	http        *http.Client
}

func New(baseURL, internalKey string, timeout time.Duration) *Client {
	return &Client{
		baseURL:     baseURL,
		internalKey: internalKey,
		http:        &http.Client{Timeout: timeout},
	}
}

// PostMultipart 文件上传（multipart/form-data）。
func (c *Client) PostMultipart(ctx context.Context, path, fileField, fileName string, fileBytes []byte, fields map[string]string, out interface{}) error {
	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	fw, err := writer.CreateFormFile(fileField, fileName)
	if err != nil {
		return apperror.ErrBadRequest.WithCause(err)
	}
	if _, err := fw.Write(fileBytes); err != nil {
		return apperror.ErrBadRequest.WithCause(err)
	}
	for k, v := range fields {
		if err := writer.WriteField(k, v); err != nil {
			return apperror.ErrBadRequest.WithCause(err)
		}
	}
	if err := writer.Close(); err != nil {
		return apperror.ErrBadRequest.WithCause(err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, &buf)
	if err != nil {
		return apperror.ErrUpstream.WithCause(err)
	}
	c.setHeaders(ctx, req)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	return c.do(req, out)
}

// PostJSON JSON POST，响应解码到 out。
func (c *Client) PostJSON(ctx context.Context, path string, payload interface{}, out interface{}) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return apperror.ErrBadRequest.WithCause(err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, bytes.NewReader(body))
	if err != nil {
		return apperror.ErrUpstream.WithCause(err)
	}
	c.setHeaders(ctx, req)
	return c.do(req, out)
}

// GetJSON GET 请求。
func (c *Client) GetJSON(ctx context.Context, path string, out interface{}) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return apperror.ErrUpstream.WithCause(err)
	}
	c.setHeaders(ctx, req)
	return c.do(req, out)
}

// StreamNDJSON POST 并按行消费 NDJSON 流；每行回调 onEvent，返回是否继续。
// 回调返回 error 时中断流并向上传递。
func (c *Client) StreamNDJSON(ctx context.Context, path string, payload interface{}, onEvent func(line []byte) error) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return apperror.ErrBadRequest.WithCause(err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, bytes.NewReader(body))
	if err != nil {
		return apperror.ErrUpstream.WithCause(err)
	}
	c.setHeaders(ctx, req)
	req.Header.Set("Accept", "application/x-ndjson")

	resp, err := c.http.Do(req)
	if err != nil {
		return apperror.ErrUpstream.WithCause(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return apperror.ErrUpstream.WithCause(fmt.Errorf("agent %s status=%d body=%s", path, resp.StatusCode, string(b)))
	}

	decoder := json.NewDecoder(resp.Body)
	for {
		var raw json.RawMessage
		if err := decoder.Decode(&raw); err != nil {
			if err == io.EOF {
				return nil
			}
			return apperror.ErrUpstream.WithCause(fmt.Errorf("ndjson decode: %w", err))
		}
		if err := onEvent(raw); err != nil {
			return err
		}
	}
}

func (c *Client) setHeaders(ctx context.Context, req *http.Request) {
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Internal-Key", c.internalKey)
	if tid := logger.TraceIDFromContext(ctx); tid != "" {
		req.Header.Set("X-Trace-Id", tid)
	}
}

func (c *Client) do(req *http.Request, out interface{}) error {
	resp, err := c.http.Do(req)
	if err != nil {
		return apperror.ErrUpstream.WithCause(err)
	}
	defer resp.Body.Close()

	b, err := io.ReadAll(io.LimitReader(resp.Body, 32<<20))
	if err != nil {
		return apperror.ErrUpstream.WithCause(err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		logger.LG().Error().Str("path", req.URL.Path).Int("status", resp.StatusCode).Str("body", truncate(string(b), 1024)).Msg("agent service error")
		return apperror.ErrUpstream.WithCause(fmt.Errorf("agent %s status=%d", req.URL.Path, resp.StatusCode))
	}
	if out == nil {
		return nil
	}
	if err := json.Unmarshal(b, out); err != nil {
		return apperror.ErrUpstream.WithCause(fmt.Errorf("decode response: %w", err))
	}
	return nil
}

func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}
