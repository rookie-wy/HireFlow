import pytest
from app.services.parsing.jd_parser import parse_jd, save_job_to_db
from app.models.schemas.job_schema import JobDescription
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_parse_jd_success(mock_llm_client, mock_guardrails):
    jd_text = "需要Python工程师"
    result = await parse_jd(jd_text)
    assert isinstance(result, JobDescription)
    assert result.title == "Engineer"
    assert "Python" in result.hard_requirements

@pytest.mark.asyncio
async def test_parse_jd_invalid_json_retry(mock_llm_client, mock_guardrails):
    # 第一次返回非法JSON，第二次正确
    mock_llm_client.completion.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content='invalid'))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content='{"title": "Engineer", "hard_requirements": ["Python"], "soft_requirements": [], "skill_graph": ["FastAPI"], "job_category": "tech"}'))])
    ]
    result = await parse_jd("Test")
    assert result.title == "Engineer"

def test_save_job_to_db(mock_db_session):
    # 测试数据库保存，不真正连接
    # mock设置
    pass