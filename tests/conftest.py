import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
sys.path.insert(0, '.')

@pytest.fixture(autouse=True)
def mock_settings():
    with patch('app.core.config.settings') as mock:
        mock.OPENAI_API_KEY = 'test-key'
        mock.LITELLM_MODEL = 'gpt-4o'
        mock.JWT_SECRET_KEY = 'test-secret'
        mock.REDIS_URL = 'redis://localhost'
        mock.DATABASE_URL = 'postgresql://localhost/test'
        yield mock

@pytest.fixture
def mock_llm_client():
    with patch('app.infrastructure.llm_client.LLMClient') as mock:
        instance = mock.return_value
        instance.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"score":90}'))]
        )
        yield instance

@pytest.fixture
def mock_db_session():
    with patch('app.db.session.get_db') as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_conn
        yield mock_conn

@pytest.fixture
def mock_redis():
    with patch('app.infrastructure.redis_client.get_redis') as mock_redis:
        yield mock_redis.return_value