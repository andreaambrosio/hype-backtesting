#!/usr/bin/env bash
# Run the full HIP-3 analysis pipeline.
# Usage: ./scripts/run_backtest.sh [--quick]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "=== hype-backtesting backtest pipeline ==="
echo "working directory: $PROJECT_ROOT"
echo ""

# Ensure dependencies
if ! python3 -c "import pandas" 2>/dev/null; then
    echo "installing python dependencies..."
    pip3 install -e ".[dev]" --quiet
fi

# Run tests first
echo "--- running tests ---"
pytest tests/ -v --tb=short
echo ""

# Run analysis
echo "--- running HIP-3 analysis ---"
python3 research/run_hip3_analysis.py

echo ""
echo "=== pipeline complete ==="
echo "charts saved to: output/"
ls -la output/*.png 2>/dev/null || echo "(no charts generated)"
