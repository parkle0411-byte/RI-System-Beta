#!/usr/bin/env bash
# 啟動壓測環境：用「正式目前正在跑」的映像（ri-backend:local、ri-frontend:local）重新標記為 stress，
# 建立全新資料庫＋migration＋db_harden（與正式相同的權限）。結束後 down.sh 刪掉。
set -euo pipefail
cd "$(dirname "$0")/../.."
export STRESS_SECRETS="${STRESS_SECRETS:-/tmp/ri-stress-secrets}"
mkdir -p "$STRESS_SECRETS"
for s in mysql_root_password mysql_app_password mysql_runtime_password django_secret_key; do
  [ -s "$STRESS_SECRETS/$s" ] || head -c 32 /dev/urandom | base64 | tr -d '/+=\n' > "$STRESS_SECRETS/$s"
done
chmod 644 "$STRESS_SECRETS"/*
docker tag ri-backend:local ri-backend:stress
docker tag ri-frontend:local ri-frontend:stress
COMPOSE=(docker compose -f qa/stress/compose.yaml)
"${COMPOSE[@]}" up -d --wait mysql backend >/dev/null 2>&1 || { "${COMPOSE[@]}" logs --tail 30; exit 1; }
for i in $(seq 1 60); do
  docker exec -e MYSQL_USER=ri_app -e MYSQL_PASSWORD_FILE=/run/secrets/mysql_app_password ri-stress-backend python manage.py migrate -v 0 >/dev/null 2>&1 && break
  [ "$i" = 60 ] && { echo "migrate 失敗"; exit 1; }; sleep 2
done
MYSQL_CONTAINER=ri-stress-mysql RUNTIME_PW_FILE="$STRESS_SECRETS/mysql_runtime_password" scripts/db_harden.sh >/dev/null
"${COMPOSE[@]}" up -d nginx >/dev/null 2>&1
echo "壓測環境已啟動（secrets: $STRESS_SECRETS）"
