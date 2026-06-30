# BlueArch CLI - Development Makefile

.PHONY: help install format lint typecheck test quality run clean venv web-build web-restart web-restar web-start web-stop

# Default target
.DEFAULT_GOAL := help

# Paths are resolved from this Makefile so targets work from repo root or
# through the wrapper at src/api/Makefile.
PROJECT_ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

# Virtual environment
VENV_PATH = $(PROJECT_ROOT)src/api/.venv
PYTHON = $(VENV_PATH)/bin/python
PIP = $(VENV_PATH)/bin/pip
API_DIR = $(PROJECT_ROOT)src/api
FRONTEND_DIR = $(PROJECT_ROOT)frontend

# Web dashboard
WEB_PORT ?= 8095
WEB_CLI_VERSION ?= v0.12.4
WEB_AUTH_DISABLED ?= true

help:  ## Show this help message
	@echo "BlueArch CLI - Development Commands"
	@echo ""
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

venv:  ## Create virtual environment
	cd $(API_DIR) && python3 -m venv .venv
	$(PIP) install --upgrade pip

install: venv  ## Install dependencies
	$(PIP) install -r $(API_DIR)/requirements.txt

install-dev: install  ## Install dev dependencies (black, flake8, mypy, pytest)
	$(PIP) install -r $(PROJECT_ROOT)dev-requirements.txt

format:  ## Format code with black
	$(PYTHON) -m black $(API_DIR)/

lint:  ## Run flake8 linting
	$(PYTHON) -m flake8 $(API_DIR)/

typecheck:  ## Run mypy type checking
	$(PYTHON) -m mypy $(API_DIR)/

test:  ## Run pytest
	cd $(API_DIR) && $(PYTHON) -m pytest

quality: format lint typecheck test  ## Run all quality checks

run:  ## Run the CLI
	cd $(API_DIR) && $(PYTHON) bluearch.py

scan:  ## Run a resource scan
	cd $(API_DIR) && $(PYTHON) bluearch.py scan

clean:  ## Clean up generated files
	find $(PROJECT_ROOT) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find $(PROJECT_ROOT) -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf $(PROJECT_ROOT).pytest_cache/ $(PROJECT_ROOT).mypy_cache/ $(PROJECT_ROOT)htmlcov/ 2>/dev/null || true

clean-all: clean  ## Clean everything including venv and frontend node_modules
	rm -rf $(VENV_PATH)
	rm -rf $(FRONTEND_DIR)/node_modules

# Frontend
web-install:  ## Install frontend dependencies
	cd $(FRONTEND_DIR) && npm install

web-build:  ## Build frontend (outputs to src/api/web/static/)
	cd $(FRONTEND_DIR) && npm run build

web-dev:  ## Start frontend dev server (with API proxy to :8095)
	cd $(FRONTEND_DIR) && npm run dev

web-start:  ## Start web dashboard (daemon mode)
	cd $(API_DIR) && BLUEARCH_WEB_AUTH_DISABLED=$(WEB_AUTH_DISABLED) BLUEARCH_CLI_VERSION=$(WEB_CLI_VERSION) $(PYTHON) bluearch.py web start --port $(WEB_PORT) --daemon

web-stop:  ## Stop web dashboard
	cd $(API_DIR) && $(PYTHON) bluearch.py web stop

web-status:  ## Show web dashboard status
	cd $(API_DIR) && $(PYTHON) bluearch.py web status

web-restart: web-build web-stop  ## Rebuild frontend and restart web server with auth enabled
	$(MAKE) -f $(PROJECT_ROOT)Makefile web-start WEB_AUTH_DISABLED=false WEB_CLI_VERSION=$(WEB_CLI_VERSION) WEB_PORT=$(WEB_PORT)

web-restar: web-restart  ## Alias for web-restart

web-create-user:  ## Create a dashboard user (interactive)
	cd $(API_DIR) && $(PYTHON) bluearch.py web create-user

# Full setup
setup: install web-install web-build  ## Complete setup (backend + frontend)
	@echo ""
	@echo "Setup complete! Next steps:"
	@echo "  make scan          # Scan AWS resources"
	@echo "  make web-start     # Start web dashboard"
	@echo "  make web-restart   # Rebuild frontend + restart"

# AWS
aws-check:  ## Check AWS configuration
	@echo "Checking AWS configuration..."
	@if [ -z "$$AWS_PROFILE" ]; then \
		echo "Warning: AWS_PROFILE not set"; \
	else \
		echo "AWS_PROFILE: $$AWS_PROFILE"; \
	fi
	cd $(API_DIR) && $(PYTHON) -c "import boto3; sts=boto3.client('sts'); id=sts.get_caller_identity(); print(f'Account: {id[\"Account\"]}')"
