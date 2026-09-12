"""专家 Agent 基类：单次 LLM 调用 + 结构化输出。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from app.core.errors import LLMError, get_logger
from app.infra.llm_client import LLMResponse, get_llm_client
from app.agents.schemas import AgentEvaluationResult

log = get_logger(__name__)


def _candidate_brief(candidate: dict, max_len: int = 1800) -> str:
    structured = candidate.get("structured_json") or {}
    import json

    try:
        structured_str = json.dumps(structured, ensure_ascii=False)[:max_len]
    except Exception:  # noqa: BLE001
        structured_str = "{}"
    resume = str(candidate.get("resume_text") or "")[:max_len]
    return f"候选人结构化信息：{structured_str}\n\n简历原文节选：{resume}"


def _jd_brief(jd: dict) -> str:
    import json

    jd_json = jd.get("jd_json") or {}
    try:
        return json.dumps(jd_json, ensure_ascii=False)[:2000]
    except Exception:  # noqa: BLE001
        return "{}"


class BaseAgent(ABC):
    """所有专家 Agent 的公共骨架。

    子类只需定义 name / persona / instruction，并可选重写 evaluate。
    """

    name: str = "base"
    persona: str = ""
    instruction: str = ""
    dimension_hint: str = ""

    def build_messages(self, jd: dict, candidate: dict) -> List[dict]:
        prompt = (
            f"{self.persona}\n\n"
            f"评估要求：{self.instruction}\n"
            f"{('评分维度建议：' + self.dimension_hint) if self.dimension_hint else ''}\n\n"
            f"岗位信息：{_jd_brief(jd)}\n\n"
            f"候选人信息：{_candidate_brief(candidate)}\n\n"
            '只返回 JSON：{"score": 0-100的整数, "dimension_scores": {"维度名": 0-100}, '
            '"evidence": ["引用简历原文的关键证据，最多3条"], "confidence": 0-1}'
        )
        return [
            {"role": "system", "content": "你是严格按 JSON 输出的招聘评估专家。"},
            {"role": "user", "content": prompt},
        ]

    def evaluate_sync(self, jd: dict, candidate: dict) -> tuple[AgentEvaluationResult, LLMResponse]:
        """同步评估（真实实现）——供 asyncio.to_thread 调用以真正并发。

        此前 evaluate 是 async 但内部调用同步 LLM，导致 gather 退化为串行。
        """
        client = get_llm_client()
        last_err: Exception | None = None
        for attempt, temperature in enumerate((0.1, 0.3)):
            try:
                data, usage = client.chat_json(self.build_messages(jd, candidate), temperature=temperature)
                return self._parse(data), usage
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                log.warning("agent %s evaluate attempt %d failed: %s", self.name, attempt + 1, exc)
        raise LLMError(f"Agent {self.name} 评估失败", cause=last_err)

    async def evaluate(self, jd: dict, candidate: dict) -> tuple[AgentEvaluationResult, LLMResponse]:
        """异步包装（线程池执行同步实现，避免阻塞事件循环）。"""
        import asyncio

        return await asyncio.to_thread(self.evaluate_sync, jd, candidate)

    def _parse(self, data: dict) -> AgentEvaluationResult:
        score = _clamp(_to_float(data.get("score"), 0))
        dims = {}
        for k, v in (data.get("dimension_scores") or {}).items():
            try:
                dims[str(k)] = _clamp(_to_float(v, 0))
            except Exception:  # noqa: BLE001
                continue
        evidence = [str(e)[:200] for e in (data.get("evidence") or []) if str(e).strip()][:3]
        confidence = min(max(_to_float(data.get("confidence"), 0.7), 0.0), 1.0)
        return AgentEvaluationResult(
            agent=self.name, score=score, dimension_scores=dims,
            evidence=evidence, confidence=confidence or 0.7,
        )


class LLMAgent(BaseAgent):
    """默认实现即 BaseAgent 的 LLM 路径。"""


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))
