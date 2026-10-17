import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    settings = Settings(
        _env_file=None,
        app_env="test",
        agent_mode="demo",
        auth_mode="demo",
        store_backend="memory",
        agent_session_backend="memory",
        enable_open_food_facts=False,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
