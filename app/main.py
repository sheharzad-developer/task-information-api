"""Application factory.

`create_app()` builds a fresh app (with its own empty store) each time it is
called, which is what the tests use to stay isolated from each other.
uvicorn loads the module-level `app`.
"""

import json
import logging
import sys
import time
import uuid

from fastapi import FastAPI, Request

from app.config import Settings, get_settings
from app.errors import register_exception_handlers
from app.repository import InMemoryTaskRepository, TaskRepository
from app.routers import health, tasks


class JsonFormatter(logging.Formatter):
    """One JSON object per line: easy to search in CloudWatch Logs Insights."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


access_logger = logging.getLogger("app.access")


def create_app(
    settings: Settings | None = None, repository: TaskRepository | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Task Management API",
        description="Task API demonstrating a Docker + GitHub Actions + AWS CI/CD pipeline.",
        version=settings.version,
    )
    app.state.settings = settings
    app.state.repository = repository or InMemoryTaskRepository()
    app.state.started_at = time.monotonic()

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # Reuse the caller's request ID (e.g. from a load balancer) or make one,
        # then echo it back so a client error can be matched to a log line.
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if request.url.path != "/health":  # keep health-check noise out of the logs
            access_logger.info(
                "request",
                extra={
                    "extra_fields": {
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    }
                },
            )
        return response

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(tasks.router)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"service": settings.app_name, "docs": "/docs", "health": "/health"}

    return app


app = create_app()
