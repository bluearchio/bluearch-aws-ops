PYTHON ?= python
VENV ?= .venv
PY := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,$(PYTHON))
PIP := $(VENV)/bin/pip

.PHONY: setup backend-dev frontend-dev test clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e . pytest pytest-mock httpx2
	cd frontend && npm ci

backend-dev:
	PYTHONPATH=src/api $(PY) -m uvicorn web.app:create_app --factory --host 127.0.0.1 --port 8095

frontend-dev:
	cd frontend && npm run dev

test:
	PYTHONPATH=src/api $(PY) -m pytest src/api/tests
	PYTHONPATH=src/api $(PY) -m compileall src/api
	cd frontend && npm run build

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache build dist *.egg-info src/*.egg-info frontend/node_modules frontend/dist frontend/.vite frontend/tsconfig.tsbuildinfo
