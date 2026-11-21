.DEFAULT_GOAL := help
UV ?= uv
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: help install run health clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "%-10s %s\\n", $$1, $$2}'

install: ## Create environment and install dependencies
	$(UV) sync

run: ## Start the UI and its PDFLens API gateway
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT)

health: ## Check this UI service
	curl --fail --silent --show-error http://127.0.0.1:$(PORT)/healthz

clean: ## Remove generated virtual environment
	rm -rf .venv
