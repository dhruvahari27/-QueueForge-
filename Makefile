PYTHON ?= python3
COMPOSE ?= docker compose

.PHONY: test lint security typecheck compose-config build up down load-test

test:
	cd backend && $(PYTHON) -m pytest -q --cov=app --cov-report=term-missing

lint:
	cd backend && ruff check app tests scripts --select E9,F63,F7,F82

security:
	cd backend && bandit -q -r app scripts

compose-config:
	$(COMPOSE) config --quiet

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

load-test:
	cd backend && $(PYTHON) scripts/load_test.py --url http://127.0.0.1:8000 --requests 200 --concurrency 10
