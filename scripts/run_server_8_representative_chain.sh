#!/usr/bin/env bash
set -Eeuo pipefail

# 服务器一键运行 8 条代表性云收费 UI 场景。

BASE="${AUTOMATION_HOME:-/home/jht/cloud-billing-ui-automation}"
IMAGE="${AUTOMATION_IMAGE:-cloud-billing-ui-test:1.3}"
ENV_FILE="${AUTOMATION_ENV_FILE:-$BASE/app/.env.standard1}"
AUTH_DIR="${AUTOMATION_AUTH_DIR:-$BASE/app/.auth}"
ARTIFACTS_DIR="${AUTOMATION_ARTIFACTS_DIR:-$BASE/artifacts}"
PORTAL_HOST="${AUTOMATION_PORTAL_HOST:-t.jslife.net}"
PORTAL_IP="${AUTOMATION_PORTAL_IP:-10.10.203.14}"

for required in "$ENV_FILE" "$AUTH_DIR"; do
  [[ -e "$required" ]] || { echo "缺少运行配置：$required" >&2; exit 2; }
done
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "找不到 Docker 镜像：$IMAGE" >&2; exit 2; }
mkdir -p "$ARTIFACTS_DIR"

echo "开始执行 8 条代表性场景（账期固定使用 2026-08）"
docker run --rm --shm-size=2g \
  --add-host "$PORTAL_HOST:$PORTAL_IP" \
  --env-file "$ENV_FILE" \
  -v "$AUTH_DIR:/opt/cloud-billing-ui-automation/.auth:ro" \
  -v "$ARTIFACTS_DIR:/opt/cloud-billing-ui-automation/artifacts" \
  "$IMAGE" python scripts/run_representative_chain.py "$@"

echo "执行完成。HTML 报告：$ARTIFACTS_DIR/representative-chain.html"
