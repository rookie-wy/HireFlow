import pytest
from app.services.screening.fine_screening import FineScreeningEngine
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_screen_candidates_cache_hit(mock_db_session):
    # 模拟缓存命中
    with patch('app.services.screening.fine_screening.init_gpt_cache') as mock_cache:
        mock_cache.return_value.get.return_value = '{"candidate_id": "1", "overall_score": 90}'
        engine = FineScreeningEngine("t1", "j1")
        reports = await engine.screen_candidates(["c1"], "sess1")
        assert len(reports) == 1
        assert reports[0].overall_score == 90

@pytest.mark.asyncio
async def test_screen_candidates_no_cache(mock_db_session, mock_llm_client):
    # 需模拟数据库、Agent等复杂流程，确保正常调用
    pass