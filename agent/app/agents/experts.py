"""专家 Agent 实现：5 个 LLM 专家 + 1 个规则型稳定性分析器。"""
from __future__ import annotations

import re
from typing import Dict, List

from app.agents.base import BaseAgent
from app.agents.schemas import AgentEvaluationResult


class InterviewerAgent(BaseAgent):
    name = "interviewer"
    persona = "你是资深技术面试官，擅长从整体经验与项目深度判断人岗匹配。"
    instruction = "综合评估候选人与岗位的匹配度：工作经验的相关性与深度、项目契合度、成长潜力。"
    dimension_hint = "experience(经验匹配), project_match(项目契合), growth_potential(成长潜力)"


class SkillEvaluationAgent(BaseAgent):
    name = "skill_evaluator"
    persona = "你是技能评估专家，熟悉技术栈深度评估。"
    instruction = "对照岗位技能图谱逐一核对候选人的技能覆盖与深度，识别核心技能缺口。"
    dimension_hint = "skill_depth(技能深度), tool_familiarity(工具熟练度)"


class CultureFitAgent(BaseAgent):
    name = "culture_fit"
    persona = "你是团队文化评估专家。"
    instruction = "对照岗位软性要求评估候选人的沟通协作与文化适配，证据需来自简历描述。"
    dimension_hint = "communication(沟通), teamwork(协作), adaptability(适应)"


class LeadershipAgent(BaseAgent):
    name = "leadership"
    persona = "你是领导力评估专家，专注管理与决策能力。"
    instruction = "基于候选人的管理经历评估团队管理规模、决策质量与业务视野。"
    dimension_hint = "team_management(团队管理), decision_making(决策), vision(视野)"


class VisualEvaluationAgent(BaseAgent):
    name = "visual_evaluator"
    persona = "你是设计作品评估专家。"
    instruction = "评估候选人的设计作品与岗位审美方向的匹配度。"
    dimension_hint = "creativity(创意), aesthetics(审美)"

    async def evaluate(self, jd: dict, candidate: dict) -> tuple[AgentEvaluationResult, "object"]:
        """优先 MCP 视觉检索，失败回退 LLM 文本评估。"""
        from app.infra.mcp_client import visual_client

        result = await visual_client().call_tool(
            "visual_search",
            {"query": str((jd.get("jd_json") or {}).get("title") or jd.get("title") or ""),
             "candidate_id": candidate.get("candidate_id") or ""},
        )
        similarity = (result or {}).get("result", {}).get("similarity") if isinstance(result, dict) else None
        if similarity is not None:
            score = min(100.0, float(similarity) * 100.0)
            return (
                AgentEvaluationResult(
                    agent=self.name, score=score,
                    dimension_scores={"visual_similarity": score},
                    evidence=[f"作品视觉相似度 {similarity}"],
                    confidence=0.8,
                ),
                None,
            )
        return await super().evaluate(jd, candidate)


class StabilityAnalyzer(BaseAgent):
    """规则型稳定性分析（零 LLM 成本）。

    补齐旧系统加权公式中 stability 维度的空缺：
      - 平均任期越长越好（>=3年高分）
      - 跳槽频繁降分（平均任期 < 1 年显著降分）
      - 长空窗期降分
    """

    name = "stability_analyzer"

    async def evaluate(self, jd: dict, candidate: dict) -> tuple[AgentEvaluationResult, None]:
        structured = candidate.get("structured_json") or {}
        experiences: List[dict] = [w for w in (structured.get("work_experience") or []) if isinstance(w, dict)]
        if not experiences:
            return AgentEvaluationResult(
                agent=self.name, score=60.0,
                dimension_scores={"tenure": 0.0, "job_changes": 0.0},
                evidence=["无工作经历信息，默认中性分"], confidence=0.3,
            ), None

        spans = sorted((_span(w) for w in experiences), key=lambda s: s[0])
        tenures = [e - s for s, e in spans if e > s]
        avg_tenure = sum(tenures) / len(tenures) if tenures else 0.0
        changes = max(len(spans) - 1, 0)

        score = 70.0
        if avg_tenure >= 3:
            score = 90.0
        elif avg_tenure >= 2:
            score = 80.0
        elif avg_tenure >= 1:
            score = 65.0
        else:
            score = 40.0
        # 空窗期扣分（每满 1 年 -8，封顶 -24）
        gaps = [max(spans[i + 1][0] - spans[i][1], 0) for i in range(len(spans) - 1)]
        gap_penalty = min(sum(g for g in gaps if g >= 1) * 8.0, 24.0)
        score = max(0.0, min(100.0, score - gap_penalty))

        evidence = [
            f"共 {len(spans)} 段工作经历，平均任期 {avg_tenure:.1f} 年",
        ]
        if gap_penalty:
            evidence.append(f"存在 {sum(1 for g in gaps if g >= 1)} 段超过 1 年的空窗期")
        return AgentEvaluationResult(
            agent=self.name,
            score=round(score, 1),
            dimension_scores={"tenure": round(avg_tenure, 1), "job_changes": float(changes)},
            evidence=evidence,
            confidence=0.9,
        ), None


def _span(w: dict) -> tuple[int, int]:
    def year(s: str) -> int:
        m = re.search(r"(20\d{2}|19\d{2})", str(s or ""))
        return int(m.group(1)) if m else 0

    start = year(w.get("start_date"))
    end = year(w.get("end_date")) or 2026
    return (start, max(end, start))
