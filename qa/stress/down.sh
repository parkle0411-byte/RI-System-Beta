#!/usr/bin/env bash
# 刪除壓測環境（容器、資料 volume、密鑰、stress 映像標籤）。
cd "$(dirname "$0")/../.."
export STRESS_SECRETS="${STRESS_SECRETS:-/tmp/ri-stress-secrets}"
mkdir -p "$STRESS_SECRETS"
docker compose -f qa/stress/compose.yaml down -v --remove-orphans >/dev/null 2>&1
rm -rf "$STRESS_SECRETS"
docker rmi ri-backend:stress ri-frontend:stress >/dev/null 2>&1 || true
echo "壓測環境已刪除"
