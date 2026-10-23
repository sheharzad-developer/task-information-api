def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "task-api"
    assert body["version"] == "test-sha"
    assert body["environment"] == "test"
    assert body["uptime_seconds"] >= 0


def test_root_points_to_docs(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_openapi_schema_is_served(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/tasks" in response.json()["paths"]


def test_request_id_is_generated(client):
    response = client.get("/health")

    assert response.headers["X-Request-ID"]


def test_request_id_is_propagated(client):
    response = client.get("/api/v1/tasks", headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"
