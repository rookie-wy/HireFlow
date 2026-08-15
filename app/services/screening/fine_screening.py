import asyncio
import hashlib
import json
import logging
from app.models.schemas.agent_schemas import OverallReport, AgentEvaluationResult
from app.services.screening.agents.agent_registry import get_agents_by_category
from app.services.screening.arbitration import debate_and_arbitrate
from app.infrastructure.gpt_cache import init_gpt_cache, get_cache_key
from app.infrastructure.llm_client import LLMClient
from app.db.repositories.match_repository import MatchRepository
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.candidate_repository import CandidateRepository
from app.db.session import get_db
from app.core.constants import DEBATE_STD_THRESHOLD
from app.core.exceptions import BusinessException

logger = logging.getLogger(__name__)

class FineScreeningEngine:
    def __init__(self, tenant_id: str, job_id: str):
        self.tenant_id = tenant_id
        self.job_id = job_id
        self.gpt_cache = init_gpt_cache()

    async def screen_candidates(self, candidate_ids: list, session_id: str, user_id: str = None) -> list[OverallReport]:
        with get_db() as conn:
            job_repo = JobRepository(conn)
            job = job_repo.find_by_id(self.job_id)
            if not job:
                raise BusinessException("Job not found")
            jd_dict = job.jd_json
            category = job.job_category

        reports = []
        for cid in candidate_ids:
            jd_hash = hashlib.md5(json.dumps(jd_dict, sort_keys=True).encode()).hexdigest()
            cache_key = get_cache_key(jd_hash, cid)
            cached = None
            if self.gpt_cache is not None:
                cached = self.gpt_cache.get(cache_key)
            if cached:
                logger.info(f"Cache hit for candidate {cid}")
                reports.append(OverallReport.parse_raw(cached))
                continue

            with get_db() as conn:
                cand_repo = CandidateRepository(conn)
                candidate = cand_repo.find_by_id(cid)
                if not candidate:
                    logger.warning(f"Candidate {cid} not found")
                    continue
                resume_dict = candidate.structured_json

            agents = get_agents_by_category(category)
            tasks = [agent.evaluate(jd_dict, resume_dict) for agent in agents]
            agent_results_list = await asyncio.gather(*tasks)
            agent_results = {agent.name: result for agent, result in zip(agents, agent_results_list)}

            final_score, dimension_scores = await debate_and_arbitrate(agent_results, jd_dict, resume_dict)
            summary = await self.generate_summary(final_score, agent_results, jd_dict, resume_dict)

            report = OverallReport(
                candidate_id=cid,
                overall_score=final_score,
                dimension_scores=dimension_scores,
                recommendation_text=summary,
                evidence=self._collect_evidence(agent_results),
                agent_details=agent_results
            )

            if self.gpt_cache is not None:
                self.gpt_cache.put(cache_key, report.json())

            with get_db() as conn:
                match_repo = MatchRepository(conn)
                match_repo.insert_from_report(report, self.tenant_id, self.job_id)

            reports.append(report)

        # 应用个性化权重（如果提供了 user_id）
        if user_id:
            from app.services.feedback.feedback_handler import apply_personalized_boost
            score_map = {r.candidate_id: r.overall_score for r in reports}
            adjusted_scores = apply_personalized_boost(user_id, score_map)
            for r in reports:
                if r.candidate_id in adjusted_scores:
                    r.overall_score = adjusted_scores[r.candidate_id]

        return reports

    async def generate_summary(self, final_score, agent_results, jd, resume):
        llm = LLMClient()
        prompt = f"""综合得分 {final_score}，各专家评价：{json.dumps({k: v.dict() for k,v in agent_results.items()}, ensure_ascii=False)}。生成一段推荐总结，50字以内。"""
        messages = [{"role": "user", "content": prompt}]
        resp = llm.completion(messages)
        return resp.choices[0].message.content

    def _collect_evidence(self, agent_results):
        ev = []
        for res in agent_results.values():
            ev.extend(res.evidence)
        return list(set(ev))