#!/usr/bin/env bash
set -euo pipefail

BASE="${AUTOMATION_HOME:-/home/jht/cloud-billing-ui-automation}"
IMAGE="${AUTOMATION_IMAGE:-cloud-billing-ui-test:1.3}"
ENV_FILE="${AUTOMATION_ENV_FILE:-$BASE/app/.env.standard1}"
PORTAL_HOST="${AUTOMATION_PORTAL_HOST:-t.jslife.net}"
PORTAL_IP="${AUTOMATION_PORTAL_IP:-10.10.203.14}"

mkdir -p "$BASE/artifacts"

exec docker run --rm --shm-size=2g \
  --add-host "$PORTAL_HOST:$PORTAL_IP" \
  --env-file "$ENV_FILE" \
  -v "$BASE/app/.auth:/opt/cloud-billing-ui-automation/.auth:ro" \
  -v "$BASE/artifacts:/opt/cloud-billing-ui-automation/artifacts" \
  "$IMAGE" \
  python scripts/run_jenkins_regression.py \
    --test-env "${TEST_ENV:-standard1}" \
    --customer-id "${CUSTOMER_ID:-93537}" \
    --account-role "${TEST_ACCOUNT_ROLE:-default}" \
    --max-minutes 0 \
    --junit \
    --html-report /opt/cloud-billing-ui-automation/artifacts/server-regression-report.html "$@"

