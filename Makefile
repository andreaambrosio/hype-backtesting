.PHONY: all test backtest lint build clean docker-up docker-down risk-build ingest-build

PYTHON  := python3
PYTEST  := pytest
CARGO   := cargo
GO      := go

# Default: run tests across all languages
all: test

# ── Python ─────────────────────────────────────────────────────────
test:
	$(PYTEST) tests/ -v --tb=short

backtest:
	$(PYTHON) research/run_hip3_analysis.py

lint:
	ruff check src/ tests/ research/
	ruff format --check src/ tests/ research/

format:
	ruff format src/ tests/ research/

# ── Rust risk engine ───────────────────────────────────────────────
risk-build:
	cd risk-engine && $(CARGO) build --release

risk-test:
	cd risk-engine && $(CARGO) test

risk-run:
	cd risk-engine && $(CARGO) run --release

# ── Go ingestion service ──────────────────────────────────────────
ingest-build:
	cd services/ingest && $(GO) build -o ../../build/ingest-svc .

ingest-test:
	cd services/ingest && $(GO) test ./...

ingest-run:
	cd services/ingest && $(GO) run .

# ── TypeScript dashboard ──────────────────────────────────────────
dashboard-install:
	cd dashboard && npm install

dashboard-dev:
	cd dashboard && npm run dev

dashboard-build:
	cd dashboard && npm run build

dashboard-lint:
	cd dashboard && npm run lint

# ── Docker ────────────────────────────────────────────────────────
docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# ── Database ──────────────────────────────────────────────────────
db-init:
	docker compose exec timescaledb psql -U quant -d quantlab -f /docker-entrypoint-initdb.d/01-schema.sql

db-analytics:
	docker compose exec timescaledb psql -U quant -d quantlab -f /sql/analytics.sql

# ── Utilities ─────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	cd risk-engine && $(CARGO) clean 2>/dev/null || true
	rm -rf build/ 2>/dev/null || true

build: risk-build ingest-build dashboard-build
	@echo "All components built."
