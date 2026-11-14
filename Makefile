.PHONY: install run web test coverage lint format docker-build docker-up docker-down clean

export PATH := $(CURDIR)/.venv/bin:$(PATH)
PYTHON ?= python
HOST ?= 0.0.0.0
PORT ?= 8000
URL ?= https://example.com

install:
	$(PYTHON) -m pip install -e '.[dev]'

run:
	seo-agent audit "$(URL)"

web:
	uvicorn seo_ai_agent.api:app --host $(HOST) --port $(PORT)

test:
	pytest

coverage:
	pytest --cov=seo_ai_agent --cov-report=term-missing --cov-fail-under=100

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

docker-build:
	docker build -t seo-ai-agent .

docker-up:
	docker compose up --build

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov build dist
