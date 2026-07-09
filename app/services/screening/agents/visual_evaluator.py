from app.services.screening.agents.base_agent import BaseAgent
from app.models.schemas.agent_schemas import AgentEvaluationResult
from app.infrastructure.llm_client import LLMClient
from app.infrastructure.mcp.base_client import MCPToolClient   # 假设使用MCP工具
import json
import logging

logger = logging.getLogger(__name__)

class VisualEvaluationAgent(BaseAgent):
    name = "visual_evaluator"

    async def evaluate(self, jd: dict, resume: dict) -> AgentEvaluationResult:
        # 设计岗需要调用 visual_search 工具获取作品集相似度
        # 这里先尝试调用MCP工具，如果失败则使用LLM进行文本评估作为后备
        try:
            visual_client = MCPToolClient("http://localhost:9002")   # 实际地址从配置读
            result = await visual_client.call_tool("visual_search", {
                "query": jd.get("title", ""),
                "candidate_id": resume.get("id", "")
            })
            if result and not result.get("error"):
                # 如果工具返回了相似度分数
                score = result.get("similarity", 50)
                return AgentEvaluationResult(
                    score=min(100, score * 100),
                    dimension_scores={"visual_match": score * 100},
                    evidence=[f"视觉相似度: {score:.2f}"],
                    confidence=0.8
                )
        except Exception as e:
            logger.warning(f"Visual search tool failed, fallback to LLM: {e}")

        # 后备：用LLM根据文本描述评估
        llm = LLMClient()
        prompt = f"""你是设计作品集评估专家。根据岗位要求和候选人的作品集描述评估匹配度。
岗位需求：{json.dumps(jd, ensure_ascii=False)}
候选人作品描述：{json.dumps(resume.get('skills', []), ensure_ascii=False)}
输出JSON：score(0-100), dimension_scores({{"creativity":0-100,"aesthetics":0-100}}), evidence, confidence"""
        messages = [{"role": "user", "content": prompt}]
        resp = llm.completion(messages)
        content = resp.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return AgentEvaluationResult(**json.loads(content))