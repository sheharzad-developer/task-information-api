import time
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness / readiness check")
def health(request: Request) -> HealthResponse:
    """Used by the Docker HEALTHCHECK, the ALB target group and the
    post-deploy smoke test in the pipeline."""
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        uptime_seconds=round(time.monotonic() - request.app.state.started_at, 2),
        timestamp=datetime.now(UTC),
    )
