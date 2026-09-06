ENV_FILE ?= .env.platform.local
DC = docker compose --env-file $(ENV_FILE) -f docker-compose.yml

.PHONY: init up down logs ps config test lint panel-build

init:
	./scripts/platform/init-local-secrets.sh

up:
	./scripts/platform/up.sh

down:
	./scripts/platform/down.sh

logs:
	$(DC) logs -f --tail=200 api panel

ps:
	$(DC) ps -a

config:
	$(DC) config --quiet

test:
	cd api && uv run pytest -q

lint:
	cd api && uv run ruff check .

panel-build:
	cd panel && npm ci && npm run build
