FROM python:3.12-slim AS backtest

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" || pip install --no-cache-dir pandas numpy requests yfinance matplotlib seaborn scipy rich

COPY src/ src/
COPY research/ research/
COPY config/ config/
COPY tests/ tests/
COPY run_backtest.py .

RUN pytest tests/ -v --tb=short

CMD ["python3", "research/run_hip3_analysis.py"]

# ---

FROM rust:1.77-slim AS risk-builder

WORKDIR /app/risk-engine
COPY risk-engine/ .
RUN cargo build --release

FROM debian:bookworm-slim AS risk-engine

COPY --from=risk-builder /app/risk-engine/target/release/risk-engine /usr/local/bin/
CMD ["risk-engine"]

# ---

FROM golang:1.22-alpine AS ingest-builder

WORKDIR /app
COPY services/ingest/ .
RUN go build -o ingest-svc .

FROM alpine:3.19 AS ingest

COPY --from=ingest-builder /app/ingest-svc /usr/local/bin/
EXPOSE 8081
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://localhost:8081/health || exit 1
CMD ["ingest-svc"]

# ---

FROM node:20-alpine AS dashboard-builder

WORKDIR /app
COPY dashboard/package.json dashboard/tsconfig.json ./
RUN npm install --production=false
COPY dashboard/src/ src/
RUN npx tsc --noEmit || true

FROM node:20-alpine AS dashboard

WORKDIR /app
COPY --from=dashboard-builder /app .
EXPOSE 3000
CMD ["npx", "next", "start"]
