#!/usr/bin/env bash
set -Eeuo pipefail

# 服务器一键运行全量云收费 UI 回归场景。
# 可通过环境变量覆盖默认路径和镜像，但通常无需修改本文件。

BASE="${AUTOMATION_HOME:-/home/jht/cloud-billing-ui-automation}"
IMAGE="${AUTOMATION_IMAGE:-cloud-billing-ui-test:1.3}"
ENV_FILE="${AUTOMATION_ENV_FILE:-$BASE/app/.env.standard1}"
AUTH_DIR="${AUTOMATION_AUTH_DIR:-$BASE/app/.auth}"
ARTIFACTS_DIR="${AUTOMATION_ARTIFACTS_DIR:-$BASE/artifacts}"
PORTAL_HOST="${AUTOMATION_PORTAL_HOST:-t.jslife.net}"
PORTAL_IP="${AUTOMATION_PORTAL_IP:-10.10.203.14}"

for required in "$ENV_FILE" "$AUTH_DIR"; do
  if [[ ! -e "$required" ]]; then
    echo "缺少运行配置：$required" >&2
    exit 2
  fi
done

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "找不到 Docker 镜像：$IMAGE" >&2
  exit 2
fi

mkdir -p "$ARTIFACTS_DIR"

echo "开始执行全量回归场景（账期固定使用 2026-08）"
echo "报告目录：$ARTIFACTS_DIR"

docker run --rm --shm-size=2g \
  --add-host "$PORTAL_HOST:$PORTAL_IP" \
  --env-file "$ENV_FILE" \
  -v "$AUTH_DIR:/opt/cloud-billing-ui-automation/.auth:ro" \
  -v "$ARTIFACTS_DIR:/opt/cloud-billing-ui-automation/artifacts" \
  "$IMAGE" \
  python scripts/run_jenkins_regression.py \
    --test-env "${TEST_ENV:-standard1}" \
    --customer-id "${CUSTOMER_ID:-93537}" \
    --account-role "${TEST_ACCOUNT_ROLE:-default}" \
    --max-minutes 0 \
    --junit \
    --html-report /opt/cloud-billing-ui-automation/artifacts/server-regression-report.html "$@"

echo
echo "执行完成。HTML 报告：$ARTIFACTS_DIR/server-regression-report.html"
echo "即时结果：$ARTIFACTS_DIR/live-results.jsonl"
echo "浏览器异常：$ARTIFACTS_DIR/browser-errors.jsonl"
