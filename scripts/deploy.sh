#!/usr/bin/env bash
# Deploy the full hype-backtesting stack via Docker Compose.
# Usage: ./scripts/deploy.sh [up|down|logs|rebuild]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

ACTION="${1:-up}"

case "$ACTION" in
    up)
        echo "starting hype-backtesting stack..."
        docker compose up -d --build
        echo ""
        echo "services:"
        echo "  dashboard:    http://localhost:3000"
        echo "  ingest:       http://localhost:8081/health"
        echo "  redis:        localhost:6379"
        echo "  timescaledb:  localhost:5432"
        ;;
    down)
        echo "stopping hype-backtesting stack..."
        docker compose down
        ;;
    logs)
        docker compose logs -f "${2:-}"
        ;;
    rebuild)
        echo "rebuilding all containers..."
        docker compose down
        docker compose build --no-cache
        docker compose up -d
        ;;
    *)
        echo "usage: $0 [up|down|logs|rebuild]"
        exit 1
        ;;
esac
