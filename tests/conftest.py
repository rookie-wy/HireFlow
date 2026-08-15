import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
sys.path.insert(0, '.')

@pytest.fixture(autouse=True)
def mock_settings():
    with patch('app.core.config.settings') as mock:
        mock.OPENAI_API_KEY = 'test-key'
        mock.DEEPSEEK_API_KEY = 'test-key'
        mock.LITELLM_MODEL = 'gpt-4o'
        mock.JWT_SECRET_KEY = 'test-secret'
        mock.REDIS_URL = 'redis://localhost'
        mock.DATABASE_URL = 'mysql+pymysql://root:password@localhost:3306/test'
        yield mock

@pytest.fixture
def mock_llm_client():
    # patch 类方法（而非整个类）：各服务模块都是 `from ... import LLMClient`，
    # 绑定的是类对象引用，patch 类本身无法拦截实例化后的调用
    with patch('app.infrastructure.llm_client.LLMClient.completion', autospec=True) as mock_completion:
        mock_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"score":90}'))]
        )
        yield mock_completion


@pytest.fixture
def mock_guardrails():
    # jd_parser 通过 `from app.infrastructure.guardrails import scan_input` 绑定引用
    with patch('app.services.parsing.jd_parser.scan_input', side_effect=lambda x: x):
        yield

@pytest.fixture
def mock_db_session():
    # 各服务模块通过 `from app.db.session import get_db` 绑定引用，patch get_db 本身无效；
    # 改为 patch get_connection（get_db 内部通过模块全局名调用）。
    with patch('app.db.session.get_connection') as mock_get_conn:
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()
        mock_get_conn.return_value = mock_conn
        yield mock_conn

@pytest.fixture
def mock_redis():
    with patch('app.infrastructure.redis_client.get_redis') as mock_redis:
        yield mock_redis.return_value