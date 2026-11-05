#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON_BIN:-$ROOT/../runtime/bin/python}"
ENVIRONMENT="${TEST_ENV:-standard1}"
CUSTOMER="${CUSTOMER_ID:-93537}"
ROLE="${TEST_ACCOUNT_ROLE:-default}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Python runtime not found: $PYTHON" >&2
  exit 2
fi

mkdir -p "$ROOT/artifacts/scheduler-logs"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$ROOT/artifacts/scheduler-logs/nightly-$STAMP.log"

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$ROOT/.cache/ms-playwright}"
cd "$ROOT"
exec "$PYTHON" scripts/run_jenkins_regression.py \
  --test-env "$ENVIRONMENT" \
  --customer-id "$CUSTOMER" \
  --account-role "$ROLE" \
  --max-minutes 0 \
  --junit \
  --html-report "$ROOT/artifacts/server-regression-report.html" \
  2>&1 | tee "$LOG"
