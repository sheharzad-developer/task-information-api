from datetime import date, timedelta
from uuid import uuid4

import pytest

from tests.conftest import TASKS_URL

TOMORROW = (date.today() + timedelta(days=1)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


# ---------- create ----------


def test_create_task_with_defaults(client):
    response = client.post(TASKS_URL, json={"title": "Write README"})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Write README"
    assert body["status"] == "todo"
    assert body["priority"] == "medium"
    assert body["description"] is None
    assert body["due_date"] is None
    assert body["created_at"] == body["updated_at"]
    assert response.headers["Location"].endswith(f"{TASKS_URL}/{body['id']}")


def test_create_task_with_all_fields(client):
    payload = {
        "title": "Deploy to ECS",
        "description": "Use Fargate",
        "status": "in_progress",
        "priority": "high",
        "due_date": TOMORROW,
    }
    response = client.post(TASKS_URL, json=payload)

    assert response.status_code == 201
    body = response.json()
    for key, value in payload.items():
        assert body[key] == value


def test_create_task_trims_whitespace(client):
    response = client.post(TASKS_URL, json={"title": "  padded  "})

    assert response.json()["title"] == "padded"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "title"),
        ({"title": ""}, "title"),
        ({"title": "   "}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"title": "ok", "description": "x" * 2001}, "description"),
        ({"title": "ok", "status": "finished"}, "status"),
        ({"title": "ok", "priority": "urgent"}, "priority"),
        ({"title": "ok", "due_date": "not-a-date"}, "due_date"),
        ({"title": "ok", "due_date": YESTERDAY}, "due_date"),
        ({"title": "ok", "owner": "someone"}, "owner"),
        ({"title": 123}, "title"),
    ],
)
def test_create_task_rejects_invalid_input(client, payload, field):
    response = client.post(TASKS_URL, json=payload)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"]
    assert any(d["field"] == field for d in error["details"]), error["details"]


def test_create_task_rejects_malformed_json(client):
    response = client.post(
        TASKS_URL, content="{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---------- read ----------


def test_get_task(client, make_task):
    task = make_task(title="Find me")

    response = client.get(f"{TASKS_URL}/{task['id']}")

    assert response.status_code == 200
    assert response.json() == task


def test_get_missing_task_returns_404(client):
    missing = uuid4()
    response = client.get(f"{TASKS_URL}/{missing}")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "task_not_found"
    assert str(missing) in error["message"]


def test_get_task_with_invalid_id_returns_422(client):
    response = client.get(f"{TASKS_URL}/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "task_id"


# ---------- list ----------


def test_list_empty(client):
    response = client.get(TASKS_URL)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_list_returns_tasks_in_creation_order(client, make_task):
    titles = ["first", "second", "third"]
    for t in titles:
        make_task(title=t)

    body = client.get(TASKS_URL).json()

    assert body["total"] == 3
    assert [t["title"] for t in body["items"]] == titles


def test_list_filters_by_status_and_priority(client, make_task):
    make_task(title="a", status="done", priority="high")
    make_task(title="b", status="done", priority="low")
    make_task(title="c", status="todo", priority="high")

    done = client.get(TASKS_URL, params={"status": "done"}).json()
    high = client.get(TASKS_URL, params={"priority": "high"}).json()
    both = client.get(TASKS_URL, params={"status": "done", "priority": "high"}).json()

    assert {t["title"] for t in done["items"]} == {"a", "b"}
    assert {t["title"] for t in high["items"]} == {"a", "c"}
    assert [t["title"] for t in both["items"]] == ["a"]


def test_list_paginates(client, make_task):
    for i in range(5):
        make_task(title=f"task {i}")

    body = client.get(TASKS_URL, params={"limit": 2, "offset": 2}).json()

    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 2
    assert [t["title"] for t in body["items"]] == ["task 2", "task 3"]


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "bogus"}, {"limit": "abc"}],
)
def test_list_rejects_invalid_query_params(client, params):
    response = client.get(TASKS_URL, params=params)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["location"] == "query"


# ---------- update ----------


def test_update_task_partially(client, make_task):
    task = make_task(title="Old title", priority="low")

    response = client.patch(f"{TASKS_URL}/{task['id']}", json={"status": "done"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["title"] == "Old title"  # untouched
    assert body["priority"] == "low"  # untouched
    assert body["updated_at"] > task["updated_at"]
    assert body["created_at"] == task["created_at"]


def test_update_can_clear_optional_fields(client, make_task):
    task = make_task(description="temp", due_date=TOMORROW)

    body = client.patch(
        f"{TASKS_URL}/{task['id']}", json={"description": None, "due_date": None}
    ).json()

    assert body["description"] is None
    assert body["due_date"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": None},
        {"status": None},
        {"title": ""},
        {"status": "nope"},
        {"due_date": YESTERDAY},
        {"unknown": 1},
    ],
)
def test_update_rejects_invalid_input(client, make_task, payload):
    task = make_task()

    response = client.patch(f"{TASKS_URL}/{task['id']}", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_update_missing_task_returns_404(client):
    response = client.patch(f"{TASKS_URL}/{uuid4()}", json={"title": "x"})

    assert response.status_code == 404


# ---------- delete ----------


def test_delete_task(client, make_task):
    task = make_task()

    response = client.delete(f"{TASKS_URL}/{task['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"{TASKS_URL}/{task['id']}").status_code == 404


def test_delete_missing_task_returns_404(client):
    response = client.delete(f"{TASKS_URL}/{uuid4()}")

    assert response.status_code == 404


# ---------- generic HTTP errors ----------


def test_unknown_route_uses_error_format(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_wrong_method_uses_error_format(client):
    response = client.put(TASKS_URL, json={})

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
