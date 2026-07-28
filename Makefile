# Fin-Content Engine — dev commands. Run from repo root.
# Windows note: `make` ships with git-bash on Windows; if `make` isn't on PATH,
# run the underlying commands directly (see each target).

.PHONY: help venv install db-up db-reset migrate test test-unit smoke clean

help:
	@echo "Targets:"
	@echo "  make venv         - create .venv (Python 3.11+)"
	@echo "  make install      - install worker deps into .venv"
	@echo "  make db-up        - start local Postgres+pgvector on :5432"
	@echo "  make db-reset     - drop and recreate fce db, apply migrations"
	@echo "  make migrate      - apply migrations to local db"
	@echo "  make test         - full test suite (needs db-up)"
	@echo "  make test-unit    - unit tests only (no DB needed)"
	@echo "  make smoke        - one ingest cycle against LIVE feeds (Layer 2)"

venv:
	python -m venv .venv

install: venv
	.venv/Scripts/python -m pip install -U pip
	.venv/Scripts/python -m pip install -e "worker[dev]"

db-up:
	docker compose up -d db
	@echo "Waiting for db health..."
	@python -c "import time,sys; [None for _ in iter(lambda: (__import__('subprocess').run(['docker','exec','fce-db','pg_isready','-U','postgres'],capture_output=True).returncode==0),None)] if False else None" || true
	@timeout 10 docker exec fce-db pg_isready -U postgres || echo "db still starting, that's ok"

db-reset: db-up
	docker exec fce-db psql -U postgres -c "DROP DATABASE IF EXISTS fce;"
	docker exec fce-db psql -U postgres -c "CREATE DATABASE fce;"
	docker exec fce-db psql -U postgres -d fce -c "CREATE EXTENSION IF NOT EXISTS vector;"
	$(MAKE) migrate

migrate:
	for f in supabase/migrations/*.sql; do \
		echo "==> applying $$f"; \
		docker exec -i fce-db psql -U postgres -d fce -v ON_ERROR_STOP=1 < $$f; \
	done

test:
	.venv/Scripts/python -m pytest worker/tests -v

test-unit:
	.venv/Scripts/python -m pytest worker/tests -v -m "not integration"

smoke:
	FCE_EMBED_MOCK=false .venv/Scripts/python -m app.smoke
