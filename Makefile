# Requires GNU make. On Windows, install via `winget install ezwinports.make` and run from Git Bash.

ifeq ($(OS),Windows_NT)
VENV_BIN := backend/.venv/Scripts
PYTHON ?= python
else
VENV_BIN := backend/.venv/bin
# Prefer 3.12/3.11 (requirements need 3.11+); fall back to python3.
PYTHON ?= $(firstword $(shell command -v python3.12 python3.11 2>/dev/null) python3)
endif
PY := $(abspath $(VENV_BIN))/python

.PHONY: install dev dev-backend dev-frontend test test-backend test-frontend build docker

install: backend/.venv frontend/node_modules

backend/.venv:
	$(PYTHON) -m venv backend/.venv
	$(PY) -m pip install -r backend/requirements.txt

frontend/node_modules:
	cd frontend && npm install

# Backend on :8000 and Vite on :5173 (which proxies /api to the backend).
dev: install
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test: install test-backend test-frontend

test-backend:
	cd backend && $(PY) -m pytest

test-frontend:
	cd frontend && npm test

# Builds the frontend into frontend/dist, which FastAPI serves at "/".
build: install
	cd frontend && npm run build

docker:
	docker compose up --build
