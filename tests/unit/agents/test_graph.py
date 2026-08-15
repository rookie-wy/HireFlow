import pytest
from app.agents.graph import app
from app.models.schemas.job_schema import JobDescription
from app.models.domain.job import Job
from app.models.schemas.agent_schemas import OverallReport
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_full_flow():
    # graph 在 import 时已用 add_node 绑定节点函数引用，patch 节点函数本身无效，
    # 因此需 patch 各节点内部依赖的底层服务，让原始节点函数走通。
    mock_jd = JobDescription(
        title="Engineer", hard_requirements=["Python"], soft_requirements=[],
        skill_graph=["FastAPI"], job_category="tech",
    )
    mock_job = Job(id="j1", tenant_id="t1", title="Engineer", jd_text="JD",
                   jd_json={"title": "Engineer"}, job_category="tech")
    mock_report = OverallReport(
        candidate_id="c1", overall_score=85, dimension_scores={},
        recommendation_text="ok", evidence=[], agent_details={},
    )

    with patch('app.agents.nodes.parse_jd.parse_jd', new_callable=AsyncMock, return_value=mock_jd), \
         patch('app.agents.nodes.parse_jd.save_job_to_db', return_value=mock_job), \
         patch('app.agents.nodes.rough_screening.HybridScreener.screen', new_callable=AsyncMock,
               return_value={"results": [{"candidate_id": "c1"}]}), \
         patch('app.agents.nodes.fine_screening.FineScreeningEngine.screen_candidates',
               new_callable=AsyncMock, return_value=[mock_report]):
        initial = {
            "tenant_id": "t1", "user_id": "u1", "session_id": "s1", "trace_id": "tr1",
            "job_id": None, "job_text": "JD", "parsed_jd": None,
            "messages": [], "candidate_ids": [], "rough_results": [], "fine_reports": [],
            "interview_draft": None, "interview_confirmed": False, "feedback": None,
            "current_step": "start",
        }
        config = {"configurable": {"thread_id": "s1"}}
        final = await app.ainvoke(initial, config)
        assert "fine_reports" in final
