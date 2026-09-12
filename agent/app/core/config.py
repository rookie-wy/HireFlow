"""Agent 服务核心配置（pydantic-settings，读 agent/.env）。"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # app/core/config.py → 上三级 = agent/ 根目录
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 基础
    app_env: str = "development"
    debug: bool = True
    agent_port: int = 8001

    # 服务间内部密钥
    agent_internal_key: str = ""

    # LLM（DeepSeek OpenAI 兼容）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_backup_models: List[str] = ["deepseek-chat"]
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2000
    llm_timeout_seconds: float = 60.0
    # 熔断：连续失败 N 次后打开，冷却 M 秒
    llm_breaker_fail_max: int = 5
    llm_breaker_reset_timeout: int = 60
    llm_retry_attempts: int = 3
    # 专家评估并发上限（DeepSeek 侧限流保护）
    llm_max_concurrency: int = 4
    # torch 线程数：多模型同进程时避免 CPU 超订（实测不限会拖慢重排 20 倍）
    torch_num_threads: int = 4

    # 成本（USD / 1M tokens，可按实际价格调整）
    llm_price_prompt_per_m: float = 0.27
    llm_price_completion_per_m: float = 1.10

    # 启动预热（后台加载 BGE 权重，把首次请求的冷启动耗时移出请求路径）
    warmup_models: bool = True
    # 向量化放后台（上传响应少等约 2s CPU 嵌入；粗筛有 BM25 兜底）
    vectorize_in_background: bool = True

    # 嵌入 / 重排
    embedding_model_path: str = "BAAI/bge-m3"
    embedding_fallback_model: str = "all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    # 简历 chunk 固定 500 字符，512 token 足够；显式限制避免长序列拖慢 CPU 推理
    embedding_max_length: int = 512
    embedding_batch_size: int = 8
    reranker_model_path: str = "BAAI/bge-reranker-v2-m3"
    # 重排成本控制：送入对数 = max_candidates × factor；单篇截断字符数（CPU 上一对约 1.5-2s）
    # 重排策略：cosine（BGE-M3 向量，CPU 上快）| cross_encoder（BGE-reranker，准但慢 3s/对）
    rerank_mode: str = "cosine"
    rerank_pairs_factor: int = 2
    rerank_doc_chars: int = 400
    rerank_query_chars: int = 256
    # 余弦重排阈值（与 cross-encoder 的 0.4 不同量纲）
    rerank_threshold_cosine: float = 0.55
    reranker_device: str = "cpu"
    hf_endpoint: str = "https://hf-mirror.com"

    # ChromaDB（本机开发约定 18001；8001 留给 agent 自身，容器内用 8000）
    chroma_host: str = "localhost"
    chroma_port: int = 18001

    # 检索参数
    rag_top_k: int = 30
    rerank_threshold: float = 0.4
    rrf_k: int = 60
    chunk_size: int = 500
    chunk_overlap: int = 50

    # 圆桌讨论
    debate_std_threshold: float = 12.0
    debate_max_rounds: int = 2
    debate_score_delta: float = 3.0
    devils_advocate_threshold: float = 80.0

    # PII
    enable_pii_masking: bool = True

    # MCP 工具
    mcp_email_url: str = "http://localhost:9000"
    mcp_calendar_url: str = "http://localhost:9001"
    mcp_visual_url: str = "http://localhost:9002"

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        os.environ.setdefault("HF_ENDPOINT", self.hf_endpoint)
        self._prefer_local_models()
        if self.app_env == "production":
            if not self.agent_internal_key:
                raise ValueError("AGENT_INTERNAL_KEY 必须在 production 环境显式配置")
            if not self.llm_api_key:
                raise ValueError("LLM_API_KEY 必须在 production 环境显式配置")
        if not self.agent_internal_key:
            self.agent_internal_key = "dev-internal-key"
        return self

    def effective_rerank_threshold(self) -> float:
        """按重排模式取阈值。

        余弦分数会被映射到 [0,1]，但分布比 cross-encoder 的 sigmoid 更集中（常见 0.5-0.8），
        直接沿用 0.4 会放行大量弱相关候选，故 cosine 模式用单独阈值（默认 0.55）。
        """
        if (self.rerank_mode or "cosine").lower() == "cosine":
            return self.rerank_threshold_cosine
        return self.rerank_threshold

    def _prefer_local_models(self) -> None:
        """本地 models/ 目录存在完整模型时优先（规避 HF 镜像 403）。"""
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models")
        weights = ("model.safetensors", "pytorch_model.bin", "model.safetensors.index.json")
        for attr, dirname in (("embedding_model_path", "bge-m3"), ("reranker_model_path", "bge-reranker-v2-m3")):
            local = os.path.join(base, dirname)
            if os.path.isdir(local) and any(os.path.isfile(os.path.join(local, w)) for w in weights):
                setattr(self, attr, local)


@lru_cache
def get_settings() -> Settings:
    return Settings()
