.PHONY: up down dev dev-restart restart logs migrate migration test test-cov shell
.PHONY: staging staging-down staging-restart logs-staging logs-staging-backend logs-staging-worker migrate-staging shell-staging

DEV_COMPOSE = docker compose -f docker-compose.yml -f docker-compose.dev.yml
STAGING_COMPOSE = docker compose -p videorecap-staging -f docker-compose.yml -f docker-compose.staging.yml

# --- Docker ---
up:
	docker compose up -d

down:
	docker compose down

dev:
	$(DEV_COMPOSE) up -d

prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

staging:
	$(STAGING_COMPOSE) up -d

staging-down:
	$(STAGING_COMPOSE) down

staging-restart:
	$(STAGING_COMPOSE) restart

# Preserves dev overrides (volume mounts, dev Dockerfile) when restarting.
# Plain `docker compose restart` would recreate containers using only the base
# docker-compose.yml, which strips the ./frontend/src:/app/src bind mount and
# leaves the container running stale source baked into the image.
dev-restart:
	$(DEV_COMPOSE) restart

restart: dev-restart

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-worker:
	docker compose logs -f worker

logs-staging:
	$(STAGING_COMPOSE) logs -f

logs-staging-backend:
	$(STAGING_COMPOSE) logs -f backend

logs-staging-worker:
	$(STAGING_COMPOSE) logs -f worker

# --- Database ---
migrate:
	docker compose exec backend bash -c "PYTHONPATH=/app alembic upgrade head"

migrate-staging:
	$(STAGING_COMPOSE) exec backend bash -c "PYTHONPATH=/app alembic upgrade head"

migration:
	docker compose exec backend bash -c "PYTHONPATH=/app alembic revision --autogenerate -m '$(msg)'"

# --- Testing ---
test:
	docker compose exec backend bash -c "PYTHONPATH=/app python -m pytest tests/ -v"

test-cov:
	docker compose exec backend bash -c "PYTHONPATH=/app python -m pytest tests/ -v --cov=app --cov-report=term-missing"

# --- Shell ---
shell:
	docker compose exec backend bash

shell-staging:
	$(STAGING_COMPOSE) exec backend bash

shell-db:
	docker compose exec postgres psql -U postgres video_recap

# --- Utilities ---
build:
	docker compose build

clean:
	docker compose down -v --remove-orphans
