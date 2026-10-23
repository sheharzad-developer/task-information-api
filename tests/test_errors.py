"""Unexpected failures must return a clean 500, never a stack trace."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repository import InMemoryTaskRepository


class ExplodingRepository(InMemoryTaskRepository):
    def list(self, **kwargs):
        raise RuntimeError("database password is hunter2")


def test_unhandled_exception_returns_generic_500():
    app = create_app(Settings(log_level="CRITICAL"), repository=ExplodingRepository())
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/tasks", headers={"X-Request-ID": "boom-1"})

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"] == "boom-1"
    assert "hunter2" not in response.text  # internal details are not leaked
