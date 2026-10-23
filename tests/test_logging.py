import json
import logging

from app.main import JsonFormatter


def test_access_log_is_one_json_line(client, caplog):
    caplog.set_level(logging.INFO, logger="app.access")

    client.get("/api/v1/tasks", headers={"X-Request-ID": "log-1"})

    record = next(r for r in caplog.records if r.name == "app.access")
    line = json.loads(JsonFormatter().format(record))
    assert line["level"] == "INFO"
    assert line["request_id"] == "log-1"
    assert line["method"] == "GET"
    assert line["path"] == "/api/v1/tasks"
    assert line["status"] == 200
    assert line["duration_ms"] >= 0


def test_health_checks_are_not_access_logged(client, caplog):
    caplog.set_level(logging.INFO, logger="app.access")

    client.get("/health")

    assert not [r for r in caplog.records if r.name == "app.access"]


def test_exceptions_are_included_in_json_logs():
    try:
        raise ValueError("bad")
    except ValueError:
        record = logging.getLogger("t").makeRecord(
            "t", logging.ERROR, __file__, 1, "failed", None, exc_info=__import__("sys").exc_info()
        )

    line = json.loads(JsonFormatter().format(record))
    assert "ValueError: bad" in line["exception"]
