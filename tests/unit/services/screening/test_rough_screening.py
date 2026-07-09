from unittest.mock import MagicMock

import pytest
from app.services.screening.rough_screening import reciprocal_rank_fusion, hyde_query_rewrite

def test_reciprocal_rank_fusion():
    dense = [{"candidate_id": "A", "score": 0.9}, {"candidate_id": "B", "score": 0.8}]
    sparse = [{"candidate_id": "B", "score": 0.7}, {"candidate_id": "C", "score": 0.6}]
    fused = reciprocal_rank_fusion(dense, sparse, k=60)
    assert fused[0] == "A" or fused[0] == "B"  # A和B总分应高于C

@pytest.mark.asyncio
async def test_hyde_query_rewrite(mock_llm_client):
    mock_llm_client.completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="理想候选人简历片段..."))]
    )
    result = await hyde_query_rewrite("3年SaaS销售")
    assert "理想" in result