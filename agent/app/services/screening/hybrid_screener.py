"""混合粗筛：硬过滤 → HyDE → 稠密(Chroma) + BM25 双路 → RRF → 重排。

修复旧系统缺口：所有结果映射真实 candidate_id；BM25 语料即候选人原文。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.core.config import get_settings
from app.core.errors import get_logger
from app.core.metrics import observe, timer
from app.infra import chroma_client, embedding_client
from app.infra.llm_client import LLMResponse, get_llm_client
from app.services.screening.bm25_index import BM25Index
from app.services.screening.hard_filter import hard_filter, skill_hit
from app.services.screening.reranker import rerank_documents

log = get_logger(__name__)

HYDE_PROMPT = """基于以下检索查询，生成一份理想候选人的简历片段（150字以内，包含技能、经验关键词），以JSON输出：{"resume": "片段内容"}

查询：{query}"""


class HybridScreener:
    """一次筛选会话：候选集在构造时给定（Go 传入，Python 无状态）。"""

    # 允许岗位级覆盖的检索/重排参数（白名单：与 agent Settings 字段同名）
    OVERRIDE_FIELDS = {
        "rag_top_k": int,
        "rerank_threshold": float,
        "rerank_threshold_cosine": float,
        "rerank_mode": str,
        "rerank_pairs_factor": int,
        "rerank_doc_chars": int,
    }

    def __init__(self, tenant_id: str, job: dict, candidates: List[dict]) -> None:
        self.tenant_id = tenant_id
        self.job = job
        self.candidates = candidates  # [{candidate_id, resume_text, structured_json}]
        self.jd_json: dict = job.get("jd_json") or {}
        self.settings = get_settings()
        # 岗位级检索/重排参数覆盖（O7）：白名单 + 类型转换，非法值忽略并告警
        self.overrides: Dict[str, object] = {}
        raw_overrides = job.get("screen_overrides") or {}
        if isinstance(raw_overrides, dict):
            for key, value in raw_overrides.items():
                caster = self.OVERRIDE_FIELDS.get(key)
                if caster is None:
                    log.warning("screen override ignored (not allowed): %s", key)
                    continue
                try:
                    self.overrides[key] = caster(value)
                except (TypeError, ValueError):
                    log.warning("screen override ignored (bad value): %s=%r", key, value)
            if self.overrides:
                log.info("job-level screen overrides: %s", self.overrides)

    def _cfg(self, name: str):
        """取参数：岗位覆盖优先，其次全局配置。"""
        if name in self.overrides:
            return self.overrides[name]
        return getattr(self.settings, name)

    # ---------- 主流程 ----------
    def screen(
        self, query: str, max_candidates: int = 10, enable_hyde: bool = True
    ) -> Tuple[List[dict], List[LLMResponse]]:
        """执行混合粗筛。

        返回 ([{candidate_id, score, reasons, evidence}], [LLMResponse])。
        全流程 candidate_id 真实映射（修复旧系统 unknown 占位问题）。
        """
        hard_requirements = self.jd_json.get("hard_requirements") or []
        skill_graph = self.jd_json.get("skill_graph") or []

        # 1. 硬性过滤
        pool = hard_filter(hard_requirements, skill_graph, self.candidates)
        if not pool:
            return [], []
        if not query:
            query = self._default_query()

        usage: List[LLMResponse] = []
        # 2. HyDE 查询改写（失败降级原查询）
        hyde_text = query
        if enable_hyde:
            rewritten, u = self._hyde_rewrite(query)
            if u is not None:
                usage.append(u)
            hyde_text = rewritten

        # 3. 双路召回（稠密检索结果同时作为重排证据）
        with timer("screen_stage_seconds", stage="dense"):
            dense_hits = self._dense_retrieval(hyde_text)
        evidence_map: Dict[str, List[str]] = {}
        for cid, _score, chunk in dense_hits:
            if chunk:
                evidence_map.setdefault(cid, []).append(chunk)

        with timer("screen_stage_seconds", stage="sparse"):
            sparse_hits = self._sparse_retrieval(query, pool)

        # 4. RRF 融合
        fused = self._rrf_fuse(dense_hits, sparse_hits)
        if not fused:
            # 双路都空（如向量库为空）：退化为按池顺序取前 N
            fused = [(c["candidate_id"], 0.0) for c in pool[: max_candidates * 2]]

        # 5. 重排（candidate 级映射）
        results = self._rerank(query, fused, pool, evidence_map, max_candidates)
        for r in results:
            r["reasons"] = self._reasons(r)
        return results, usage

    # ---------- 分批粗筛（O4：打破 200 人上限） ----------
    def screen_batch(
        self, query: str, query_vec: Optional[List[float]], hyde_text: str
    ) -> Tuple[List[dict], Dict[str, List[str]]]:
        """单批召回：硬过滤 → 稠密 + 稀疏 → RRF。返回 (融合结果, 证据映射)。

        查询向量由调用方跨批次共享（避免每批重复嵌入查询）。
        """
        hard_requirements = self.jd_json.get("hard_requirements") or []
        skill_graph = self.jd_json.get("skill_graph") or []

        pool = hard_filter(hard_requirements, skill_graph, self.candidates)
        if not pool:
            return [], {}

        with timer("screen_stage_seconds", stage="dense"):
            dense_hits = self._dense_retrieval_with_vec(query_vec)
        evidence_map: Dict[str, List[str]] = {}
        for cid, _score, chunk in dense_hits:
            if chunk:
                evidence_map.setdefault(cid, []).append(chunk)

        with timer("screen_stage_seconds", stage="sparse"):
            sparse_hits = self._sparse_retrieval(query, pool)

        fused = self._rrf_fuse(dense_hits, sparse_hits)
        if not fused:
            # 双路都空（向量库为空 / 全部未命中）：退化为池内顺序，保证不漏人
            fused = [(c["candidate_id"], 0.0) for c in pool]

        results = [
            {"candidate_id": cid, "score": round(score, 6), "rrf_score": round(score, 6)}
            for cid, score in fused
        ]
        return results, evidence_map

    def finalize_ranking(
        self,
        query: str,
        merged: Dict[str, dict],
        by_id: Dict[str, dict],
        evidence_map: Dict[str, List[str]],
        max_candidates: int,
    ) -> List[dict]:
        """跨批次统一重排：按 RRF 分取候选面 → 重排 → 返回 top N。"""
        if not merged:
            return []
        fused = sorted(
            ((cid, float(r.get("rrf_score") or r.get("score") or 0.0)) for cid, r in merged.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        pool = [by_id[cid] for cid, _ in fused if cid in by_id]
        return self._rerank(query, fused, pool, evidence_map, max_candidates)

    # ---------- 各阶段 ----------
    def _default_query(self) -> str:
        parts = [str(self.job.get("title") or "")]
        parts += [str(s) for s in (self.jd_json.get("skill_graph") or [])][:10]
        parts += [str(s) for s in (self.jd_json.get("hard_requirements") or [])][:5]
        return " ".join(p for p in parts if p)

    def _hyde_rewrite(self, query: str) -> Tuple[str, Optional[LLMResponse]]:
        try:
            data, usage = get_llm_client().chat_json(
                [{"role": "user", "content": HYDE_PROMPT.format(query=query[:1000])}],
                temperature=0.2,
                max_tokens=300,
            )
            text = str(data.get("resume") or data.get("text") or "").strip()
            if not text and data:
                text = str(next(iter(data.values()), ""))[:500]
            return (text or query), usage
        except Exception as exc:  # noqa: BLE001
            log.warning("HyDE rewrite failed, fallback to raw query: %s", exc)
            return query, None

    def _dense_retrieval(self, query_text: str) -> List[Tuple[str, float, str]]:
        """Chroma 稠密检索（自行嵌入查询）。"""
        vec = embedding_client.embed_texts([query_text])
        if vec is None:
            return []
        return self._dense_retrieval_with_vec(vec[0])

    def _dense_retrieval_with_vec(self, query_vec: Optional[List[float]]) -> List[Tuple[str, float, str]]:
        """用给定查询向量做稠密检索 → [(candidate_id, score, chunk)]。失败降级为空（BM25 兜底）。"""
        import time as _t

        if query_vec is None:
            log.warning("dense retrieval skipped (no query vector)")
            return []
        t0 = _t.perf_counter()
        try:
            hits = chroma_client.query_resumes(self.tenant_id, query_vec, self._cfg('rag_top_k'))
        except Exception as exc:  # noqa: BLE001 降级：Chroma 故障不阻塞粗筛
            log.warning("dense retrieval unavailable (chroma error: %s)", exc)
            return []
        log.info("dense retrieval: chroma_query=%.2fs hits=%d", _t.perf_counter() - t0, len(hits))
        return [(h["candidate_id"], h["score"], h["chunk"]) for h in hits if h["candidate_id"]]

    def _sparse_retrieval(self, query: str, pool: List[dict]) -> List[Tuple[str, float, str]]:
        """BM25 over 候选人原文 → [(candidate_id, score, "")]。索引槽位直接绑定候选人。"""
        index = BM25Index([c.get("resume_text") or "" for c in pool])
        hits = index.search(query, self._cfg('rag_top_k'))
        return [(pool[i]["candidate_id"], score, "") for i, score in hits]

    def _rrf_fuse(
        self,
        dense: List[Tuple[str, float, str]],
        sparse: List[Tuple[str, float, str]],
    ) -> List[Tuple[str, float]]:
        """RRF：score(d) = Σ 1/(k + rank)。"""
        k = self.settings.rrf_k
        scores: Dict[str, float] = {}
        for ranked in (dense, sparse):
            for rank, (cid, _score, _chunk) in enumerate(ranked):
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    def _rerank(
        self,
        query: str,
        fused: List[Tuple[str, float]],
        pool: List[dict],
        evidence_map: Dict[str, List[str]],
        max_candidates: int,
    ) -> List[dict]:
        """候选级证据重排：有 reranker 用其分数（阈值过滤），否则回退 RRF 分。

        性能（实测）：CPU 上 BGE-reranker 一对「查询+长文档」约 1.5–2s，
        此前取 `max_candidates*3` 对、每篇截断 1000 字符，30 对要 40–60s，是粗筛阶段最大瓶颈。
        优化：送入对数降到 `max_candidates*2`（粗筛只需选出前 N，不必对全量精排），
        文档截断降到 `rerank_doc_chars`（默认 400 字符，覆盖技能与经历关键句已足够）。
        """
        by_id = {c["candidate_id"]: c for c in pool}
        from app.services.screening.reranker import effective_mode

        factor = int(self._cfg('rerank_pairs_factor'))
        if effective_mode() == "cosine":
            factor = max(factor, 4)  # 向量重排成本极低，扩大候选面提升召回
        top_n = max(1, max_candidates * factor)
        doc_chars = self._cfg('rerank_doc_chars')

        pairs: List[List[str]] = []
        cids: List[str] = []
        for cid, _rrf in fused[:top_n]:
            cand = by_id.get(cid)
            if cand is None:
                continue
            doc = (evidence_map.get(cid) or [cand.get("resume_text") or ""])[0][:doc_chars]
            pairs.append([query[: self.settings.rerank_query_chars], doc])
            cids.append(cid)

        with timer("screen_stage_seconds", stage="rerank"):
            rerank_scores = rerank_documents(query, [p[1] for p in pairs]) if pairs else None
        observe("rerank_pairs", float(len(pairs)))

        fused_score = dict(fused)
        results: List[dict] = []
        for i, cid in enumerate(cids):
            if rerank_scores is not None:
                score = float(rerank_scores[i])
                if score < self._effective_threshold():
                    continue
            else:
                score = fused_score.get(cid, 0.0)
            results.append(
                {
                    "candidate_id": cid,
                    "score": round(score, 4),
                    "rrf_score": round(fused_score.get(cid, 0.0), 6),
                    "evidence": [e[:200] for e in evidence_map.get(cid, [])[:3]],
                }
            )
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_candidates]

    def _effective_threshold(self) -> float:
        """重排阈值：按最终生效模式选择（cosine 与 cross-encoder 分数量纲不同）。

        模式解析顺序必须与重排实现（reranker.effective_mode）一致：
        岗位覆盖 > 会话覆盖 > 全局配置；否则会出现"按 cosine 算分、按 cross 取阈值"的错配。
        """
        from app.services.screening.reranker import effective_mode

        override_mode = self.overrides.get("rerank_mode")
        mode = str(override_mode or effective_mode()).lower()
        if mode == "cosine":
            return float(self._cfg("rerank_threshold_cosine"))
        return float(self._cfg("rerank_threshold"))

    def _reasons(self, result: dict) -> List[str]:
        reasons: List[str] = []
        structured = next(
            (c.get("structured_json") or {} for c in self.candidates if c["candidate_id"] == result["candidate_id"]),
            {},
        )
        skills = {str(s).strip().lower() for s in structured.get("skills") or []}
        text = str(result.get("evidence", [""])[0]).lower() if result.get("evidence") else ""
        graph = [str(s) for s in self.jd_json.get("skill_graph") or []]
        # 与硬过滤同一套匹配规则，保证「入池理由」和「过滤依据」不会互相打脸
        matched = [g for g in graph if skill_hit(g, skills, text)]
        if matched:
            reasons.append(f"技能匹配：{', '.join(matched[:5])}")
        if result.get("evidence"):
            reasons.append(f"原文证据：{result['evidence'][0][:80]}")
        return reasons
