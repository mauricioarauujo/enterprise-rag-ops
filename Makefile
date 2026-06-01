.PHONY: help sync format lint test clean download-data check-data build-index rebuild-index build-index-gold retrieval-smoke smoke retrieval-eval eval-baseline install-hooks trace-up trace-reset export-traces classify

# Documents kept per source type when building the corpus subset.
DOCS_PER_SOURCE ?= 100
export DOCS_PER_SOURCE

RESULTS_FILE ?= results/baseline.jsonl
export RESULTS_FILE

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

build-index-gold:  ## Fetch HF data using --gold-aware and rebuild the index
	uv run rag-ingest --gold-aware
	uv run rag-index --force

retrieval-smoke:  ## Run the BGE-M3 Recall@k smoke gate on the fixed question subset (local-only)
	uv run pytest tests/retrieval/test_retrieval_smoke.py -m smoke

retrieval-eval:  ## Run the retrieval-level threshold sweep over the evaluation set
	uv run python src/enterprise_rag_ops/eval/threshold_sweep.py

smoke:  ## Run the end-to-end rag-ask smoke on 10 questions (requires OPENAI_API_KEY + built index)
	uv run pytest tests/generation/test_generation_smoke.py -m smoke

eval-baseline:  ## Run the multi-model baseline evaluation sweep (requires API keys + gold index)
	uv run rag-eval run --config configs/baseline.yaml

export-traces:  ## Export traces and scores from results JSONL file to local Arize Phoenix
	uv run rag-export-traces --results $(RESULTS_FILE)

classify:  ## Classify failure modes in results JSONL file using rag-classify
	uv run rag-classify --results $(RESULTS_FILE)

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

install-hooks:  ## Activate the pre-commit framework in this clone (run once per clone)
	uv run pre-commit install

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +

trace-up:  ## Start the Arize Phoenix Docker container locally
	docker compose -f infra/phoenix/docker-compose.yml up -d

trace-reset:  ## Reset the Arize Phoenix container by destroying volumes and restarting
	docker compose -f infra/phoenix/docker-compose.yml down -v
	docker compose -f infra/phoenix/docker-compose.yml up -d
