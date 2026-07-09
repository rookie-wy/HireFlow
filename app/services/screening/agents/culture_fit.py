from app.services.screening.agents.base_agent import BaseAgent
from app.models.schemas.agent_schemas import AgentEvaluationResult
from app.infrastructure.llm_client import LLMClient
import json

class CultureFitAgent(BaseAgent):
    name = "culture_fit"

    async def evaluate(self, jd: dict, resume: dict) -> AgentEvaluationResult:
        llm = LLMClient()
        prompt = f"""你是企业文化契合度评估专家。根据岗位要求推断团队文化，评估候选人的软性技能匹配度。
岗位要求（软性）：{json.dumps(jd.get('soft_requirements', []), ensure_ascii=False)}
候选人简历片段：{json.dumps(resume, ensure_ascii=False, default=str)}
输出JSON，包含：
- score: 0-100 总分
- dimension_scores: {{"communication": 0-100, "teamwork": 0-100, "adaptability": 0-100}}
- evidence: 关键证据列表
- confidence: 0-1 置信度
"""
        messages = [{"role": "user", "content": prompt}]
        resp = llm.completion(messages)
        content = resp.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return AgentEvaluationResult(**json.loads(content))