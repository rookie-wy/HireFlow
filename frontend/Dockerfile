# syntax=docker/dockerfile:1
# =============================================================================
# frontend（React18 + Vite5 + TS + AntD5）生产镜像
#
# 构建（**构建上下文是仓库根目录**，因为要 COPY deploy/nginx.conf；
# 由 deploy/docker-compose.yml 自动处理，手动构建时）：
#   docker build -f frontend/Dockerfile -t ai-recruitment/frontend:latest .
#
# 为什么上下文是根目录而不是 frontend/：
#   nginx 站点配置按约定放在 deploy/nginx.conf，构建时需要把它 COPY 进镜像；
#   docker 不允许 COPY 越出构建上下文（../deploy/nginx.conf 会直接报错），
#   所以把上下文提升到根目录，用 frontend/ 前缀取前端源码。
#   根目录的 .dockerignore 已排除 agent/models、*.venv、node_modules 等大目录，
#   不会把 6.5GB 模型塞进构建缓存。
#
# 产物链：node:22-alpine 执行 npm run build（tsc -b && vite build）得到 frontend/dist，
#         再整体拷进 nginx:1.27-alpine 由 nginx 托管静态文件并反代 /api → backend:8080。
# =============================================================================

# ---------- 构建阶段 ----------
FROM node:22-alpine AS builder

# 国内 npm 镜像；要切回官方源删掉这一行即可。
# 不要设 NODE_ENV=production，否则 vite/tsc 这些 devDependencies 会被裁掉导致构建失败。
ENV npm_config_registry=https://registry.npmmirror.com

WORKDIR /app

# 先只拷依赖清单，利用层缓存；有 lock 文件时用 npm ci 保证版本可复现
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# 再拷前端源码与构建配置
COPY frontend/ ./

# tsc -b && vite build → 输出 /app/dist
RUN npm run build

# ---------- 运行阶段 ----------
FROM nginx:1.27-alpine

# nginx 站点配置：SPA history 回退 + /api 反代 + SSE 关闭缓冲
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

# 静态产物
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

# nginx:alpine 自带前台运行 CMD，无需覆写
