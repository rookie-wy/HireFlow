from abc import ABC, abstractmethod
from app.models.schemas.agent_schemas import AgentEvaluationResult

class BaseAgent(ABC):
    name: str = "base_agent"

    @abstractmethod
    async def evaluate(self, jd: dict, resume: dict) -> AgentEvaluationResult:
        pass