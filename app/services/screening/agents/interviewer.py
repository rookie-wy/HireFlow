from app.services.screening.agents.base_agent import BaseAgent
from app.models.schemas.agent_schemas import AgentEvaluationResult
from app.infrastructure.llm_client import LLMClient
import json


class InterviewerAgent(BaseAgent):
    name = "interviewer"

    async def evaluate(self, jd: dict, resume: dict) -> AgentEvaluationResult:
        llm = LLMClient()
        prompt = f"""
        你是资深面试官，评估候选人与岗位的匹配度。
        JD: {json.dumps(jd, ensure_ascii=False)}
        简历摘要: {json.dumps(resume, ensure_ascii=False)}

        请输出JSON，包含：
        - score: 0-100 总分
        - dimension_scores: {{"experience": 0-100, "project_match": 0-100, "growth_potential": 0-100}}
        - evidence: 关键证据列表（引用简历内容）
        - confidence: 0-1 置信度
        """
        messages = [{"role": "user", "content": prompt}]
        resp = llm.completion(messages)
        content = resp.choices[0].message.content
        data = json.loads(content)
        return AgentEvaluationResult(**data)