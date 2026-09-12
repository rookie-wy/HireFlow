# syntax=docker/dockerfile:1
# =============================================================================
# agent（Python 3.13 / FastAPI AI 能力服务）生产镜像
#
# 构建（构建上下文必须是 agent/）：
#   docker build -f agent/Dockerfile -t ai-recruitment/agent:latest agent
#
# ---------------------------------------------------------------------------
# 依赖安装方式（二选一）。**当前仓库状态下默认走 B（pip），因为 A 还缺前置文件。**
#
# A. uv sync --frozen（可复现性最好，补齐锁文件后推荐切到这里）
#    前提：构建上下文里必须有 **agent/uv.lock**（与 agent/pyproject.toml 同目录）。
#    ⚠️ 当前仓库只有**根目录** uv.lock，而它属于根项目 pythonproject2
#       （52 个依赖，含 streamlit / langgraph / litellm 等 agent 用不到的重包），
#       不是 agent 项目的锁文件；uv 也不会向上级目录寻找锁文件。
#    ⇒ 启用 A 之前先在 agent/ 目录生成并提交锁文件：
#         cd agent && uv lock
#      然后把下面 B 的两行换成：
#         COPY pyproject.toml uv.lock /app/
#         RUN uv sync --frozen --no-dev --no-install-project
#
# B. pip install（默认，当前即可构建）
#    说明：pyproject.toml 里的 [[tool.uv.index]] 只对 uv 生效，
#          pip 必须显式用 -i 指定国内源（华为云），否则默认走 PyPI 会很慢。
#          torch / FlagEmbedding / sentence-transformers 体积大，本层构建耗时会较长。
# ---------------------------------------------------------------------------
#
# 重要：本镜像 **不 COPY 本地模型**（agent/models/ 下 bge-m3 + reranker 合计约 6.5GB），
#       一律通过 compose 的 bind mount 在运行期挂载到 /app/models。
#       app/core/config.py 的 _prefer_local_models() 会自动探测
#       /app/models/bge-m3 与 /app/models/bge-reranker-v2-m3，
#       只要目录里存在 model.safetensors / pytorch_model.bin / *.index.json 就优先用本地权重，
#       从而规避 HuggingFace 镜像 403 问题（国内推荐路径）。
# =============================================================================

FROM python:3.13-slim

# PYTHONUNBUFFERED：日志实时刷到 stdout，docker logs 才能看到实时输出
# PYTHONDONTWRITEBYTECODE：不生成 .pyc，镜像层更干净
# UV_PROJECT_ENVIRONMENT：uv 直接把依赖装进系统 Python（/usr/local），
#   uvicorn 在 PATH 上即可找到，不需要激活 venv
# HF_HOME：HuggingFace 缓存目录，指向独立可写路径 /app/model_cache
#   （**不能**放在 /app/models 下面：compose 把本地模型以 :ro 只读挂载到那里，
#    只读文件系统上写缓存会直接报错，且缓存会被 bind mount 遮住）
# HF_ENDPOINT：国内镜像兜底（有本地模型时实际不会触发下载）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_HTTP_TIMEOUT=300 \
    UV_INDEX_URL=https://repo.huaweicloud.com/repository/pypi/simple \
    VIRTUAL_ENV=/usr/local \
    HF_HOME=/app/model_cache \
    HF_ENDPOINT=https://hf-mirror.com

# 运行期系统依赖：
#   curl             —— 容器探活用
#   libgomp1         —— torch / sentence-transformers 的 OpenMP 运行时（缺了会 import 失败）
#   libgl1 libglib2.0-0 —— opencv 系（图像处理 / 可选 OCR）的动态库
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# uv 官方静态二进制。当前默认走方式 B（pip）用不到它；
# 保留是为了切到方式 A（uv sync --frozen）时无需改这一层，也便于进容器排障。
# 想减小镜像可删掉本行（约 30MB）。
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /usr/local/bin/

WORKDIR /app

# ---- 依赖安装（方式 B：pip；切到方式 A 见文件头部说明）-----------------------
# 先只拷 pyproject.toml → 装依赖 → 再拷源码：改业务代码不会重装 torch 这类大依赖。
# 说明：此时目录下还没有 app/ 包，但 setuptools 会正常构建出一个不含源码的 wheel
#       （实测可过），依赖解析完全由 pyproject.toml 的 dependencies 决定；
#       源码由下一步 COPY app 提供，uvicorn 在 WORKDIR /app 下以 app.main:app 导入。
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir \
        -i https://repo.huaweicloud.com/repository/pypi/simple \
        --trusted-host repo.huaweicloud.com \
        /app

# ---- 业务源码 ---------------------------------------------------------------
COPY app /app/app

# 模型挂载点（运行期由 compose 覆盖；先建目录，保证单独 docker run 时也不报路径不存在）
RUN mkdir -p /app/models/bge-m3 /app/models/bge-reranker-v2-m3 /app/model_cache

# 非 root 运行（与 backend 保持同一 uid/gid，宿主机挂载目录权限更好处理）
# /app/model_cache 需要可写（HF 缓存），/app/models 运行期是只读挂载
RUN groupadd -g 10001 app && useradd -u 10001 -g app -M -s /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

EXPOSE 8001

# 存活探针（/healthz 免内部密钥；返回体带 checks{llm_config, chroma}，
# 依赖异常时 status=degraded 但仍返回 200，这里只判 HTTP 可达）
# start-period 给到 180s：首次加载 BGE-M3 + Reranker 权重在 CPU 上可能 1~3 分钟
HEALTHCHECK --interval=20s --timeout=8s --start-period=180s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8001/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
