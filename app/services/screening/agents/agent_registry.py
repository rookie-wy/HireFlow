from app.models.enums import JobCategory
from app.services.screening.agents.interviewer import InterviewerAgent
from app.services.screening.agents.skill_evaluator import SkillEvaluationAgent
from app.services.screening.agents.culture_fit import CultureFitAgent
from app.services.screening.agents.leadership import LeadershipAgent
from app.services.screening.agents.visual_evaluator import VisualEvaluationAgent

AGENT_MAP = {
    JobCategory.TECH: [InterviewerAgent(), SkillEvaluationAgent(), CultureFitAgent()],
    JobCategory.MANAGEMENT: [InterviewerAgent(), LeadershipAgent(), CultureFitAgent()],
    JobCategory.DESIGN: [InterviewerAgent(), SkillEvaluationAgent(), VisualEvaluationAgent()],
    JobCategory.GENERAL: [InterviewerAgent(), CultureFitAgent()],
}

def get_agents_by_category(category):
    # 如果传入的是字符串，转换为枚举
    if isinstance(category, str):
        try:
            category = JobCategory(category)
        except ValueError:
            category = JobCategory.GENERAL
    return AGENT_MAP.get(category, AGENT_MAP[JobCategory.GENERAL])