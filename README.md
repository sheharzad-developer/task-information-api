# Task API — FastAPI · Docker · GitHub Actions · AWS ECS Fargate

A small task-management REST API with a complete CI/CD pipeline: every pull
request is linted, tested and built into a Docker image that gets smoke-tested;
every merge to `main` pushes that exact image to Amazon ECR and rolls it out to
ECS Fargate behind an Application Load Balancer, with no AWS keys stored in
GitHub.

```
 git push ──► GitHub Actions ──► test ──► build + smoke-test image ──► push to ECR ──► deploy to ECS Fargate ──► verify live /health
```

| Document | What's in it |
|---|---|
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Step-by-step: local run → Docker → GitHub → AWS → first automated deploy → rollback → teardown |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Diagrams, components, and why each design choice was made |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Symptom → cause → fix, for every stage of the pipeline |

## API

Interactive docs at `/docs` (Swagger UI) and `/redoc` once the app is running.

| Method | Path | Description | Success |
|---|---|---|---|
| `GET` | `/health` | Health check (status, version, environment, uptime) | 200 |
| `POST` | `/api/v1/tasks` | Create a task | 201 + `Location` header |
| `GET` | `/api/v1/tasks` | List tasks. Query: `status`, `priority`, `limit` (1–100, default 20), `offset` | 200 |
| `GET` | `/api/v1/tasks/{id}` | Get one task | 200 |
| `PATCH` | `/api/v1/tasks/{id}` | Update some fields | 200 |
| `DELETE` | `/api/v1/tasks/{id}` | Delete a task | 204 |

**Task fields:** `title` (required, 1–200 chars, trimmed), `description` (≤ 2000),
`status` (`todo` · `in_progress` · `done`), `priority` (`low` · `medium` · `high`),
`due_date` (ISO date, not in the past). Unknown fields are rejected.

**Errors** always have the same shape, and every response carries an `X-Request-ID` header that also appears in the logs:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "request_id": "4abc1fb8-b087-4e1b-8946-7707843da2a5",
    "details": [
      { "field": "title", "location": "body", "message": "String should have at least 1 character", "type": "string_too_short" }
    ]
  }
}
```

| Status | `code` | When |
|---|---|---|
| 404 | `task_not_found` / `not_found` | Unknown task ID / unknown route |
| 405 | `method_not_allowed` | Wrong HTTP method |
| 422 | `validation_error` | Bad body, query parameter or path parameter |
| 500 | `internal_error` | Unexpected failure (logged with stack trace; details never sent to the client) |

## Quick start

```bash
# Run locally
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
make test        # 50 tests, ~99% coverage
make run         # http://localhost:8000/docs

# Run in Docker
docker compose up --build
curl http://localhost:8000/health
```

Try it:

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Write the report", "priority": "high"}'

curl "http://localhost:8000/api/v1/tasks?status=todo&limit=10"
```

## Project layout

```
.
├── app/
│   ├── main.py            # app factory, request-ID middleware, JSON logging
│   ├── config.py          # settings from environment variables
│   ├── models.py          # Pydantic schemas = input validation
│   ├── repository.py      # storage interface + in-memory implementation
│   ├── errors.py          # exception handlers → one consistent error format
│   └── routers/
│       ├── health.py
│       └── tasks.py
├── tests/                 # pytest suite (API, validation, errors, logging)
├── Dockerfile             # multi-stage, non-root, healthcheck
├── docker-compose.yml     # local container run
├── .github/workflows/
│   └── ci-cd.yml          # test → build → push to ECR → deploy to ECS
├── infra/cloudformation/
│   ├── 01-bootstrap.yml   # ECR repo + GitHub OIDC deploy role
│   └── 02-app.yml         # VPC, ALB, ECS cluster/service, logs
├── docs/
├── Makefile
├── pyproject.toml         # pytest, coverage (≥90% enforced), ruff config
├── requirements.txt       # runtime deps (go in the image)
└── requirements-dev.txt   # test/lint deps (CI only)
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `task-api` | Shown in `/health` |
| `ENVIRONMENT` | `local` | Shown in `/health` |
| `APP_VERSION` | `1.0.0` | Set to the git commit SHA by the pipeline |
| `LOG_LEVEL` | `INFO` | Python log level |
| `PORT` | `8000` | Container listen port |

## Known limitation

Tasks are stored in memory, so they reset whenever the container restarts or a
new version deploys, and the ECS service runs exactly one task. The route
handlers depend only on the `TaskRepository` interface, so moving to DynamoDB or
RDS means adding one class. See [ARCHITECTURE.md](docs/ARCHITECTURE.md#next-steps-for-production).
