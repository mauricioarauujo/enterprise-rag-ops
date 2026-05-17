.PHONY: help sync format lint test verify clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

sync:  ## Install/sync dependencies via uv
	uv sync --group dev

format:  ## Format code with ruff and Markdown with prettier
	uv run ruff format src tests
	uv run ruff check --fix src tests
	npx prettier --write "**/*.md" --ignore-path .gitignore --log-level warn

lint:  ## Lint code with ruff and Markdown with prettier (no auto-fix)
	uv run ruff format --check src tests
	uv run ruff check src tests
	npx prettier --check "**/*.md" --ignore-path .gitignore --log-level warn

test:  ## Run tests with pytest
	uv run pytest

test-cov:  ## Run tests with coverage report
	uv run pytest --cov --cov-report=term-missing

verify: lint test  ## Full quality pipeline (lint + test)

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
