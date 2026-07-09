from app.services.screening.agents.base_agent import BaseAgent
from app.models.schemas.agent_schemas import AgentEvaluationResult
from app.infrastructure.llm_client import LLMClient
import json

class SkillEvaluationAgent(BaseAgent):
    name = "skill_evaluator"

    async def evaluate(self, jd: dict, resume: dict) -> AgentEvaluationResult:
        llm = LLMClient()
        prompt = f"""你是技能评估专家，评估候选人技术栈与岗位的匹配度。
岗位要求：{json.dumps(jd.get('skill_graph', []), ensure_ascii=False)}
候选人技能：{json.dumps(resume.get('skills', []), ensure_ascii=False)}
输出JSON，含 score(0-100), dimension_scores(如 {{"skill_depth":80, "tool_familiarity":85}}), evidence(列表), confidence(0-1)。"""
        messages = [{"role": "user", "content": prompt}]
        resp = llm.completion(messages)
        content = resp.choices[0].message.content.strip()
        return AgentEvaluationResult(**json.loads(content))