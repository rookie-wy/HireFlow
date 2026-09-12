"""Moderator（主持人）：分歧检测、圆桌讨论、魔鬼代言人、加权仲裁。

四阶段协议（v5 §4.3）：
  Stage 1 独立评估（引擎层并行执行，此处接收结果）
  Stage 2 分歧检测（零 LLM：置信度加权均值 + 标准差）
  Stage 3 圆桌讨论（<=2 轮，摘要卡交换；全体 >=80 时注入魔鬼代言人）
  Stage 4 仲裁（类别权重 x 置信度加权，真实公式）
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional, Tuple

from app.agents.experts import StabilityAnalyzer
from app.agents.schemas import (
    AgentEvaluationResult,
    DiscussionMeta,
    DiscussionTranscript,
    DiscussionTurn,
)
from app.core.config import get_settings
from app.core.errors import get_logger
from app.infra.llm_client import LLMResponse, get_llm_client

log = get_logger(__name__)

DISCUSS_PROMPT = """你是圆桌评审中的{agent_name}。此前你对该候选人给出了 {own_score:.0f} 分。

其他专家的观点摘要：
{peer_cards}

{devil_note}
请基于同伴的证据重新审视你的判断：
- 若维持原判（stance=maintain），请强化你的论证；
- 若需要修正（stance=revise），给出新分数与理由；禁止无理由改分。

只返回 JSON：{{"stance": "maintain|revise", "score": 0-100, "dimension_scores": {{}}, "evidence": ["最多2条"], "reasoning": "50字以内"}}"""

DEVIL_ADVOCATE_PROMPT = """你是圆桌评审中的「魔鬼代言人」。当前所有专家对候选人的打分都偏高（均分 {mean:.0f}）。
你的职责是系统性唱反调，对抗群体乐观偏差：找出这份简历被高估的理由——技能宽泛但深度不足、经历包装痕迹、与 JD 核心要求的错配、稳定性风险等。
基于候选人材料给出你的质疑论据（不需要提出最终分数）。

岗位信息：{jd}
候选人信息：{candidate}

只返回 JSON：{{"argument": "最强的一条质疑论据（80字以内）", "evidence": ["简历原文证据1条"]}}"""

RECOMMEND_PROMPT = """基于以下多专家评估结论，为该候选人写一段不超过 80 字的招聘推荐语（中文，直接陈述结论与核心理由，不要客套）。

岗位：{job_title}
综合得分：{overall:.1f}
各专家结论：{experts}
关键证据：{evidence}

只返回 JSON：{{"recommendation": "推荐语"}}"""


class ModeratorAgent:
    """无个人打分立场，只做流程控制与最终仲裁。"""

    name = "moderator"

    # ---------- Stage 2: 分歧检测 ----------
    def detect_divergence(self, results: List[AgentEvaluationResult]) -> Tuple[float, float, bool]:
        """返回 (加权均值, 标准差, 是否需要讨论)。

        规则型稳定性分不参与分歧判定（无 LLM 噪声，不构成分歧信号）。
        """
        s = get_settings()
        llm_results = [r for r in results if r.agent != "stability_analyzer"]
        if len(llm_results) <= 1:
            return (llm_results[0].score if llm_results else 0.0, 0.0, False)
        weights = [max(r.confidence, 0.1) for r in llm_results]
        values = [r.score for r in llm_results]
        mean = sum(v * w for v, w in zip(values, weights)) / sum(weights)
        std = statistics.pstdev(values)
        needs = std > s.debate_std_threshold
        return mean, std, needs

    # ---------- Stage 3: 圆桌讨论 ----------
    async def run_discussion(
        self,
        results: List[AgentEvaluationResult],
        jd: dict,
        candidate: dict,
        initial_mean: float,
        initial_std: float,
    ) -> Tuple[List[AgentEvaluationResult], DiscussionTranscript, List[Optional[LLMResponse]]]:
        """返回 (最终各 Agent 结果, 讨论记录, 用量列表)。"""
        s = get_settings()
        expert_results = [r for r in results if r.agent != "stability_analyzer"]
        stability = next((r for r in results if r.agent == "stability_analyzer"), None)

        transcript = DiscussionTranscript(meta=DiscussionMeta(
            initial_mean=initial_mean, initial_std=initial_std,
            initial_scores={r.agent: r.score for r in results},
        ))
        usages: List[Optional[LLMResponse]] = []
        devil_used = False

        # 魔鬼代言人：共识过热时注入（每候选最多一次，第 1 轮前）
        devil_argument = ""
        if expert_results and min(r.score for r in expert_results) >= s.devils_advocate_threshold:
            devil_used = True
            devil_argument, u = await self._devil_advocate(jd, candidate, initial_mean)
            usages.append(u)
            transcript.turns.append(DiscussionTurn(
                round=0, agent="devils_advocate", stance="advocate",
                content=devil_argument, score=None, score_delta=None,
            ))

        current = list(expert_results)
        convergence = "max_rounds"
        for round_no in range(1, s.debate_max_rounds + 1):
            next_round: List[AgentEvaluationResult] = []
            for r in current:
                updated, u = await self._discuss_turn(r, current, jd, candidate, devil_argument, round_no)
                usages.append(u)
                next_round.append(updated)
                transcript.turns.append(DiscussionTurn(
                    round=round_no, agent=r.agent, stance=updated.stance or "maintain",
                    content=updated.reasoning or "",
                    score=updated.score,
                    score_delta=round(updated.score - r.score, 2),
                ))
            current = next_round

            mean, std = self._mean_std(current)
            max_delta = max(abs(t.score - o.score) for t, o in zip(current, expert_results[: len(current)]))
            expert_results = current
            if std <= s.debate_std_threshold:
                convergence = "converged"
                break
            if round_no > 1 and max_delta <= s.debate_score_delta:
                convergence = "converged"
                break

        final = list(expert_results)
        if stability is not None:
            final.append(stability)

        final_mean, final_std = self._mean_std(expert_results)
        transcript.meta.rounds = len({t.round for t in transcript.turns if t.agent != "devils_advocate"})
        transcript.meta.convergence = "consensus" if not transcript.meta.rounds else convergence
        transcript.meta.devil_advocate_used = devil_used
        transcript.meta.final_mean = final_mean
        transcript.meta.final_std = final_std
        transcript.meta.final_scores = {r.agent: r.score for r in final}
        return final, transcript, usages

    async def _discuss_turn(
        self, own: AgentEvaluationResult, peers: List[AgentEvaluationResult],
        jd: dict, candidate: dict, devil_argument: str, round_no: int,
    ) -> Tuple[AgentEvaluationResult, Optional[LLMResponse]]:
        client = get_llm_client()
        peer_cards = "\n".join(
            f"- {p.agent}：{p.score:.0f} 分（置信度 {p.confidence:.1f}），证据：{(p.evidence[0] if p.evidence else '无')}"
            for p in peers if p.agent != own.agent
        ) or "（无其他专家）"
        devil_note = f"魔鬼代言人提出质疑：{devil_argument}\n请认真对待该质疑。" if devil_argument else ""
        messages = [{"role": "user", "content": DISCUSS_PROMPT.format(
            agent_name=own.agent, own_score=own.score, peer_cards=peer_cards,
            devil_note=devil_note,
        )}]
        try:
            data, usage = client.chat_json(messages, temperature=0.2, max_tokens=400)
        except Exception as exc:  # noqa: BLE001
            log.warning("discuss turn failed for %s: %s", own.agent, exc)
            return own.model_copy(update={"round": round_no}), None

        stance = str(data.get("stance") or "maintain")
        if stance not in ("maintain", "revise"):
            stance = "maintain"
        new_score = own.score
        if stance == "revise":
            try:
                new_score = float(data.get("score"))
            except (TypeError, ValueError):
                stance, new_score = "maintain", own.score
        dims = dict(own.dimension_scores)
        for k, v in (data.get("dimension_scores") or {}).items():
            try:
                dims[str(k)] = max(0.0, min(100.0, float(v)))
            except (TypeError, ValueError):
                continue
        evidence = list(own.evidence)
        for e in (data.get("evidence") or []):
            if str(e).strip() and str(e)[:200] not in evidence:
                evidence.append(str(e)[:200])
        reasoning = str(data.get("reasoning") or "")[:150]
        return own.model_copy(update={
            "score": max(0.0, min(100.0, new_score)),
            "stance": stance, "reasoning": reasoning, "round": round_no,
            "dimension_scores": dims, "evidence": evidence[:3],
        }), usage

    async def _devil_advocate(self, jd: dict, candidate: dict, mean: float) -> Tuple[str, Optional[LLMResponse]]:
        client = get_llm_client()
        import json

        messages = [{"role": "user", "content": DEVIL_ADVOCATE_PROMPT.format(
            mean=mean,
            jd=json.dumps(jd.get("jd_json") or {}, ensure_ascii=False)[:800],
            candidate=json.dumps(candidate.get("structured_json") or {}, ensure_ascii=False)[:1200],
        )}]
        try:
            data, usage = client.chat_json(messages, temperature=0.6, max_tokens=300)
            return str(data.get("argument") or ""), usage
        except Exception as exc:  # noqa: BLE001
            log.warning("devil advocate failed: %s", exc)
            return "", None

    # ---------- Stage 4: 仲裁 ----------
    def arbitrate(
        self, results: List[AgentEvaluationResult], category: str, weights: Dict[str, float]
    ) -> Tuple[float, Dict[str, float]]:
        """类别权重 x 置信度加权（真实公式，修复旧系统平均分问题）。

        魔鬼代言人不参与加权（对抗角色，刻意压低，纳入会扭曲）。
        """
        num = 0.0
        den = 0.0
        dims_acc: Dict[str, List[float]] = {}
        for r in results:
            w = weights.get(r.agent)
            if w is None:  # 未登记权重的角色（如魔鬼代言人）不参与
                continue
            conf = max(min(r.confidence, 1.0), 0.1)
            num += w * conf * r.score
            den += w * conf
            for dim, val in r.dimension_scores.items():
                if isinstance(val, (int, float)):
                    dims_acc.setdefault(dim, []).append(float(val))
        overall = num / den if den > 0 else 0.0
        dimension_scores = {k: round(sum(v) / len(v), 1) for k, v in dims_acc.items()}
        return round(overall, 1), dimension_scores

    async def generate_recommendation(
        self, jd: dict, overall: float, results: List[AgentEvaluationResult], top_evidence: List[str],
    ) -> Tuple[str, Optional[LLMResponse]]:
        client = get_llm_client()
        experts = "; ".join(f"{r.agent}={r.score:.0f}分" for r in results)
        evidence = " | ".join(top_evidence[:3]) or "无"
        messages = [{"role": "user", "content": RECOMMEND_PROMPT.format(
            job_title=str((jd.get("jd_json") or {}).get("title") or jd.get("title") or "目标岗位"),
            overall=overall, experts=experts, evidence=evidence,
        )}]
        try:
            data, usage = client.chat_json(messages, temperature=0.3, max_tokens=200)
            return str(data.get("recommendation") or "").strip(), usage
        except Exception as exc:  # noqa: BLE001
            log.warning("recommendation generation failed: %s", exc)
            return "", None

    @staticmethod
    def _mean_std(results: List[AgentEvaluationResult]) -> Tuple[float, float]:
        scores = [r.score for r in results]
        if not scores:
            return 0.0, 0.0
        return statistics.mean(scores), statistics.pstdev(scores)
