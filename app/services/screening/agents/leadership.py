from app.services.screening.agents.base_agent import BaseAgent
from app.models.schemas.agent_schemas import AgentEvaluationResult
from app.infrastructure.llm_client import LLMClient
import json

class LeadershipAgent(BaseAgent):
    name = "leadership"

    async def evaluate(self, jd: dict, resume: dict) -> AgentEvaluationResult:
        llm = LLMClient()
        prompt = f"""你是领导力评估专家，评估候选人的管理经验和团队领导能力。
岗位要求：{json.dumps(jd, ensure_ascii=False, default=str)}
候选人经历：{json.dumps(resume.get('work_experience', []), ensure_ascii=False, default=str)}
输出JSON：
- score: 0-100
- dimension_scores: {{"team_management": 0-100, "decision_making": 0-100, "vision": 0-100}}
- evidence: 列表
- confidence: 0-1
"""
        messages = [{"role": "user", "content": prompt}]
        resp = llm.completion(messages)
        content = resp.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return AgentEvaluationResult(**json.loads(content))