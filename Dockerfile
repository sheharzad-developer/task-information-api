# syntax=docker/dockerfile:1

# ---------- Stage 1: build dependencies into a virtualenv ----------
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
# Copy only the requirements first so this layer is cached until they change.
COPY requirements.txt .
RUN pip install -r requirements.txt


# ---------- Stage 2: slim runtime image ----------
FROM python:3.13-slim AS runtime

# Set by the pipeline (git SHA); shows up in /health.
ARG APP_VERSION=dev

LABEL org.opencontainers.image.title="task-api" \
      org.opencontainers.image.description="FastAPI task management API" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_VERSION=${APP_VERSION} \
    PORT=8000

# Run as an unprivileged user, never as root.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app

# Numeric UID so platforms can verify it is non-root without reading /etc/passwd.
USER 10001:10001
EXPOSE 8000

# python:slim has no curl, so use the standard library for the health check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4).status == 200 else 1)"]

# exec form: uvicorn is PID 1 and receives SIGTERM directly, so ECS can stop
# tasks gracefully. --proxy-headers trusts X-Forwarded-* from the load balancer.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
