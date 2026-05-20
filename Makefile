.PHONY: help sync format lint test verify clean download-data check-data build-index rebuild-index retrieval-smoke

# Documents kept per source type when building the corpus subset.
DOCS_PER_SOURCE ?= 100
export DOCS_PER_SOURCE

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

sync:  ## Install/sync dependencies via uv
	uv sync --group dev

download-data:  ## Fetch EnterpriseRAG-Bench and write the stratified corpus (DOCS_PER_SOURCE=N)
	uv run rag-ingest --docs-per-source $(DOCS_PER_SOURCE)

check-data:  ## Validate the local corpus offline (no network)
	uv run pytest tests/ingest/test_corpus.py -m corpus

build-index:  ## Build BM25 + dense + LanceDB indices over data/processed/corpus.jsonl (idempotent)
	uv run rag-index

rebuild-index:  ## Force a clean rebuild of all retrieval artifacts
	uv run rag-index --force

retrieval-smoke:  ## Run the BGE-M3 Recall@k smoke gate on the fixed question subset (local-only)
	uv run pytest tests/retrieval/test_retrieval_smoke.py -m smoke

format:  ## Format code with ruff and Markdown with prettier
	uv run ruff format src tests
	uv run ruff check --fix src tests
	npx prettier --write "**/*.md" --ignore-path .gitignore --log-level warn

lint:  ## Lint code with ruff and Markdown with prettier (no auto-fix)
	uv run ruff format --check src tests
	uv run ruff check src tests
	npx prettier --check "**/*.md" --ignore-path .gitignore --log-level warn

test:  ## Run tests with pytest (excludes live-corpus and real-model smoke — see check-data / retrieval-smoke)
	uv run pytest -m "not corpus and not smoke"

test-cov:  ## Run tests with coverage report
	uv run pytest -m "not corpus and not smoke" --cov --cov-report=term-missing

verify: lint test  ## Full quality pipeline (lint + test)

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
