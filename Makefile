IMAGE ?= task-api:local

.PHONY: install lint format test run docker-build docker-run smoke

install:        ## Install app + dev dependencies
	pip install -r requirements-dev.txt

lint:           ## Lint and check formatting (same as CI)
	ruff check .
	ruff format --check .

format:         ## Auto-format the code
	ruff format .
	ruff check --fix .

test:           ## Run tests with coverage (same as CI)
	pytest --cov --cov-report=term-missing

run:            ## Run the API locally with auto-reload
	uvicorn app.main:app --reload --port 8000

docker-build:   ## Build the Docker image
	docker build --build-arg APP_VERSION=local -t $(IMAGE) .

docker-run:     ## Run the image on port 8000
	docker run --rm -p 8000:8000 --name task-api $(IMAGE)

smoke:          ## Hit the running API's health endpoint
	curl -fsS http://localhost:8000/health
