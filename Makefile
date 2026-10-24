.DEFAULT_GOAL := help

UV ?= uv
PYTHON ?= 3.14
VENV ?= .venv314
HOST ?= 127.0.0.1
PORT ?= 8000

# Keep every uv command on the same project environment.
UV_ENV = UV_PROJECT_ENVIRONMENT=$(VENV)

.PHONY: help install run dev health clean

help: ## Show available project commands
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create the Python environment and install project dependencies with uv
	$(UV_ENV) $(UV) sync --python $(PYTHON) --extra dev

run: ## Run the API server
	$(UV_ENV) $(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT)

dev: ## Run the API server with automatic reload
	$(UV_ENV) $(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

health: ## Check the local health endpoint
	curl --fail --silent --show-error http://$(HOST):$(PORT)/healthz

clean: ## Remove the configured virtual environment
	rm -rf $(VENV)
