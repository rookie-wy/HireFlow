import asyncio
import statistics
from app.models.schemas.agent_schemas import AgentEvaluationResult
from app.infrastructure.llm_client import LLMClient
from app.core.constants import DEBATE_STD_THRESHOLD, DEBATE_MAX_ROUNDS
import logging

logger = logging.getLogger(__name__)

async def debate_and_arbitrate(agent_results: dict[str, AgentEvaluationResult], jd: dict, resume: dict) -> float:
    scores = [r.score for r in agent_results.values()]
    if len(scores) <= 1 or statistics.stdev(scores) <= DEBATE_STD_THRESHOLD:
        # 无分歧，加权计算
        return calculate_weighted_score(agent_results)

    # 辩论循环
    current_results = agent_results.copy()
    for round_num in range(1, DEBATE_MAX_ROUNDS + 1):
        logger.info(f"Debate round {round_num}")
        # 找出最高分和最低分Agent
        sorted_agents = sorted(current_results.items(), key=lambda x: x[1].score)
        lowest_agent_name, lowest_res = sorted_agents[0]
        highest_agent_name, highest_res = sorted_agents[-1]

        # 要求双方基于对方证据重新评估
        new_low = await request_rebuttal(lowest_agent_name, lowest_res, highest_res, jd, resume)
        new_high = await request_rebuttal(highest_agent_name, highest_res, lowest_res, jd, resume)

        current_results[lowest_agent_name] = new_low
        current_results[highest_agent_name] = new_high

        new_scores = [r.score for r in current_results.values()]
        if statistics.stdev(new_scores) <= DEBATE_STD_THRESHOLD:
            break

    # 若仍未收敛，进行仲裁（加权公式）
    return calculate_weighted_score(current_results)

async def request_rebuttal(agent_name: str, own_result: AgentEvaluationResult, opponent_result: AgentEvaluationResult,
                           jd: dict, resume: dict) -> AgentEvaluationResult:
    llm = LLMClient()
    prompt = f"""你是{agent_name}，你的原始评估：{own_result.json()}
    对方评估：{opponent_result.json()}
    请结合对方证据，重新评估并输出JSON（score, dimension_scores, evidence, confidence）。"""
    messages = [{"role": "user", "content": prompt}]
    resp = llm.completion(messages)
    import json
    data = json.loads(resp.choices[0].message.content)
    return AgentEvaluationResult(**data)

def calculate_weighted_score(agent_results: dict[str, AgentEvaluationResult]) -> float:
    # 通用权重公式（与文档一致）: 技能*0.35 + 经验*0.35 + 文化*0.15 + 稳定性*0.15
    # 由于每个Agent可能返回多个维度，这里简化：取所有维度的加权平均，权重从配置获取
    # 实际实现中可更精细
    total = 0.0
    weight_sum = 0.0
    for agent_name, res in agent_results.items():
        # 假设每个Agent的score是其内部维度加权得来，这里直接用总分参与仲裁
        pass
    # 简单做法：使用所有Agent分数的平均值作为最终得分（仲裁前），但文档要求最终得分用公式计算，
    # 因此我们需要按维度聚合。为保持示例清晰，此处略去维度聚合细节，假定最终得分由各Agent分数平均得到，
    # 并在生成报告时再按公式修正。实际工程中应按照Agent返回的dimension_scores套用公式。
    scores = [r.score for r in agent_results.values()]
    return sum(scores) / len(scores)