import pytest
from app.agents.graph import app
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_full_flow():
    # 构建初始状态并运行图，由于涉及大量外部调用，需要mock多个服务
    with patch('app.agents.nodes.parse_jd.parse_jd', new_callable=AsyncMock) as mock_parse, \
         patch('app.agents.nodes.rough_screening.rough_screening_node', new_callable=AsyncMock) as mock_rough, \
         patch('app.agents.nodes.fine_screening.fine_screening_node', new_callable=AsyncMock) as mock_fine, \
         patch('app.agents.nodes.schedule.schedule_node', new_callable=AsyncMock) as mock_sched, \
         patch('app.agents.nodes.feedback.feedback_node', new_callable=AsyncMock) as mock_fb:
        mock_parse.return_value = {"job_id": "j1", "parsed_jd": {}}
        mock_rough.return_value = {"candidate_ids": ["c1"], "rough_results": [{}]}
        mock_fine.return_value = {"fine_reports": [{"candidate_id": "c1", "overall_score": 85}]}
        mock_sched.return_value = {"interview_draft": {}}
        mock_fb.return_value = {}

        initial = {"tenant_id": "t1", "user_id": "u1", "session_id": "s1", "trace_id": "tr1",
                   "job_text": "JD", "messages": [], "current_step": "start"}
        config = {"configurable": {"thread_id": "s1"}}
        final = await app.ainvoke(initial, config)
        assert "fine_reports" in final