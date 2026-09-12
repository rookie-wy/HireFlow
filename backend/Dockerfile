# syntax=docker/dockerfile:1
# =============================================================================
# backend（Go / Gin 业务中台）生产镜像
#
# 构建（在项目根目录执行，构建上下文必须是 backend/）：
#   docker build -f backend/Dockerfile -t ai-recruitment/backend:latest backend
# 或直接由 deploy/docker-compose.yml 构建（context: ../backend）。
#
# 说明：
#   1) Go 版本以 backend/go.mod 为准（当前 go 1.24），构建镜像用 golang:1.24-alpine。
#   2) CGO_ENABLED=0 产出静态可执行文件，运行镜像里没有 libc 也能跑。
#   3) 依赖层（go.mod/go.sum）单独 COPY，改业务代码不会重新下载依赖。
#   4) 运行镜像只含二进制 + CA 证书 + tzdata + wget（wget 供 HEALTHCHECK/编排探活）。
#   5) 数据库表结构由程序启动时的内嵌迁移自动创建（7 张表），无需迁移容器。
# =============================================================================

# ---------- 构建阶段 ----------
FROM golang:1.24-alpine AS builder

# GOPROXY：国内网络必须走 goproxy.cn，否则拉依赖会超时；GOSUMDB 保持默认校验。
# CGO_ENABLED=0：纯静态编译，运行阶段可换任意精简基础镜像。
ENV CGO_ENABLED=0 \
    GOOS=linux \
    GOPROXY=https://goproxy.cn,direct \
    GOMODCACHE=/go/pkg/mod \
    GOCACHE=/root/.cache/go-build

WORKDIR /build

# 先只拷依赖清单，利用层缓存
COPY go.mod go.sum ./
RUN go mod download

# 再拷源码编译
COPY . .

# -trimpath 去掉本地绝对路径；-s -w 去掉符号表与调试信息，镜像更小。
RUN go build -trimpath -ldflags="-s -w" -o /build/server ./cmd/server

# ---------- 运行阶段 ----------
FROM alpine:3.20

# tzdata：容器内时区正确（日志时间、JWT 过期、筛选任务超时都依赖本地时间）
# ca-certificates：访问 DeepSeek API / 其他 HTTPS 依赖必需
# wget：容器探活用（busybox 自带）
RUN apk add --no-cache ca-certificates tzdata wget && \
    addgroup -g 10001 -S app && \
    adduser -u 10001 -S app -G app

WORKDIR /app
COPY --from=builder /build/server /app/server
# 运行期以非 root 用户执行，降低容器逃逸风险
RUN chown -R app:app /app
USER app

EXPOSE 8080

# 注意：这里用 /healthz（存活探针，只反映进程状态）。
# 就绪探针请用 /readyz（会检查 mysql/redis/agent 三项依赖），
# compose 里对 backend 的 healthcheck 用的也是 /healthz，
# 避免 agent 尚未就绪时把 backend 标记成 unhealthy 造成依赖链死锁。
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

# 容器里通过环境变量注入配置（internal/config 的 .env 读取只在本机开发时才需要）
CMD ["/app/server"]
