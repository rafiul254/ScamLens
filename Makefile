# ScamLens — one-command local development
# `make dev` starts the FastAPI backend (:8000) and the Vite PWA (:5173) together.

SHELL := /bin/bash
PY ?= python3
PORT_API ?= 8000
PORT_WEB ?= 5173

.PHONY: help setup setup-backend setup-frontend dev dev-backend dev-frontend \
        train train-text train-url data test test-backend test-frontend \
        lint typecheck build preview docker docker-up clean reset-db

help:
	@echo "ScamLens targets:"
	@echo "  make setup           install backend + frontend dependencies"
	@echo "  make data            download the real datasets (SMS spam, SpamAssassin, PhiUSIIL)"
	@echo "  make train           build the datasets and train BOTH models (writes ml/artifacts/)"
	@echo "  make dev             run the API and the web app together (the main command)"
	@echo "  make test            backend pytest + frontend vitest"
	@echo "  make build           production build of the frontend"
	@echo "  make docker-up       docker compose up (API + web, production build)"
	@echo "  make clean           remove caches and build output"

# --------------------------------------------------------------------- setup
setup: setup-backend setup-frontend

setup-backend:
	$(PY) -m pip install -r backend/requirements.txt
	@echo "Optional (embedding backend + comparison metrics): $(PY) -m pip install -r ml/requirements-ml.txt"

setup-frontend:
	cd frontend && npm install

# ---------------------------------------------------------------------- data
data:
	bash ml/download_data.sh

train: train-url train-text

train-text:
	$(PY) ml/build_text_dataset.py
	$(PY) ml/train_text_model.py

train-url:
	$(PY) ml/build_url_dataset.py --sample-per-class 30000
	$(PY) ml/train_url_model.py

# ----------------------------------------------------------------------- dev
dev:
	@echo "API  → http://localhost:$(PORT_API)/docs"
	@echo "Web  → http://localhost:$(PORT_WEB)"
	@(trap 'kill 0' INT TERM; \
	  $(MAKE) dev-backend & \
	  $(MAKE) dev-frontend & \
	  wait)

dev-backend:
	cd backend && $(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port $(PORT_API)

dev-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port $(PORT_WEB)

# --------------------------------------------------------------------- tests
test: test-backend test-frontend

test-backend:
	cd backend && $(PY) -m pytest tests -q

test-frontend:
	cd frontend && npx vitest run

typecheck:
	cd frontend && npx tsc --noEmit

build:
	cd frontend && npm run build

preview: build
	cd frontend && npm run preview -- --port 4173

# -------------------------------------------------------------------- docker
docker:
	docker build -t scamlens .

docker-up:
	docker compose up --build

# --------------------------------------------------------------------- chores
clean:
	rm -rf frontend/dist frontend/node_modules/.vite backend/.pytest_cache \
	       backend/app/__pycache__ backend/app/**/__pycache__ .pytest_cache

reset-db:
	rm -f backend/app/scamlens.db backend/app/scamlens.db-wal backend/app/scamlens.db-shm
