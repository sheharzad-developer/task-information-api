import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TASKS_URL = "/api/v1/tasks"


@pytest.fixture
def app():
    # A new app per test means a new, empty in-memory store per test.
    return create_app(Settings(environment="test", version="test-sha", log_level="WARNING"))


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_task(client):
    def _make(**overrides):
        payload = {"title": "Sample task", **overrides}
        response = client.post(TASKS_URL, json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return _make
