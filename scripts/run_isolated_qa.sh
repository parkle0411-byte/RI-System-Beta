#!/usr/bin/env bash
# 一鍵在「獨立測試環境」執行全部資料庫／API 測試組（backend/qa/suites）。正式資料庫與容器完全不動。
#
#   scripts/run_isolated_qa.sh                    全部測試組（約 30–40 分鐘）
#   scripts/run_isolated_qa.sh cases_api swiss_facility   只跑列出的測試組
#   KEEP=1 scripts/run_isolated_qa.sh ...         結束後保留環境（除錯用；之後 docker compose -p ri-isoqa down -v）
#
# 做法：用目前的原始碼建一個專用映像 ri-backend:isoqa（不影響正式的 ri-backend:local），起一套隔離的 MySQL＋後端，
# 後端以 ri_runtime 連線並套用 db_harden.sh 的權限與 Audit trigger（與正式相同），Audit 記錄啟用、RI_DISPOSABLE_QA=true。
# 有些測試組會提交資料，所以「每個測試組前都重建一個全新的資料庫」。任何一組失敗就以非 0 結束。
set -uo pipefail
cd "$(dirname "$0")/.."
GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'
ISOQA_SECRETS="$(mktemp -d)"; export ISOQA_SECRETS
COMPOSE=(docker compose -f qa/isolated/compose.yaml)
cleanup() {
  if [ "${KEEP:-0}" != "1" ]; then "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1; fi
  rm -rf "$ISOQA_SECRETS"
}
trap cleanup EXIT
for s in mysql_root_password mysql_app_password mysql_runtime_password django_secret_key; do
  head -c 32 /dev/urandom | base64 | tr -d '/+=\n' > "$ISOQA_SECRETS/$s"
done
chmod 644 "$ISOQA_SECRETS"/*   # 容器內以非 root 讀取（隨機值，結束即刪）

echo "== 建立測試映像（目前原始碼）並啟動獨立環境 =="
docker build -q -t ri-backend:isoqa backend >/dev/null || { echo "映像建置失敗"; exit 1; }
"${COMPOSE[@]}" up -d --wait >/dev/null 2>&1 || { echo "測試環境啟動失敗"; "${COMPOSE[@]}" logs --tail 40; exit 1; }

fresh_db() {
  # MySQL 初始化期間是只接受本機、還沒設 root 密碼的暫時伺服器，重試到 root 真的能登入為止
  for i in $(seq 1 60); do
    out=$(docker exec ri-isoqa-mysql sh -c 'mysql -uroot -p"$(cat /run/secrets/mysql_root_password)" -e "DROP DATABASE IF EXISTS ri_system; CREATE DATABASE ri_system CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; GRANT ALL ON ri_system.* TO ri_app@\"%\";" 2>&1' | grep -v "Using a password")
    [ -z "$out" ] && break
    [ "$i" = 60 ] && { echo "無法重建測試資料庫: $out"; return 1; }
    sleep 2
  done
  # migration 以擁有者 ri_app 執行（MySQL 初始化期間健康檢查就會通過，所以重試到真的連得上）
  for i in $(seq 1 60); do
    docker exec -e MYSQL_USER=ri_app -e MYSQL_PASSWORD_FILE=/run/secrets/mysql_app_password ri-isoqa-backend \
      python manage.py migrate -v 0 >/dev/null 2>&1 && break
    [ "$i" = 60 ] && { echo "資料庫一直無法連線或 migrate 失敗"; return 1; }
    sleep 2
  done
  MYSQL_CONTAINER=ri-isoqa-mysql RUNTIME_PW_FILE="$ISOQA_SECRETS/mysql_runtime_password" scripts/db_harden.sh >/dev/null || { echo "db_harden 失敗"; return 1; }
}

if [ "$#" -gt 0 ]; then SUITES=("$@"); else SUITES=($(ls backend/qa/suites/*.py | xargs -n1 basename | sed 's/\.py$//')); fi
echo "== 資料庫／API 測試組（${#SUITES[@]} 組，每組全新資料庫）=="
FAILED=0
for name in "${SUITES[@]}"; do
  f="backend/qa/suites/$name.py"
  [ -f "$f" ] || { printf "  %s%-32s 找不到%s\n" "$RED" "$name" "$OFF"; FAILED=1; continue; }
  fresh_db || { FAILED=1; break; }
  envs=(); [ "$name" = auth_permissions ] && envs=(-e RI_LOGIN_THROTTLE=10/min)   # 這組要驗證預設的登入限流
  out=$(docker exec -i "${envs[@]}" ri-isoqa-backend python manage.py shell < "$f" 2>&1 | grep -v -i "warn\|imported auto")
  line=$(grep -E "passed" <<<"$out" | head -1)
  if [ -n "$line" ] && ! grep -q "^FAIL" <<<"$out"; then printf "  %s%-32s %s%s\n" "$GREEN" "$name" "$line" "$OFF"
  else printf "  %s%-32s 失敗%s\n" "$RED" "$name" "$OFF"; grep -E "^FAIL|Error|assert" <<<"$out" | tail -6 | cut -c1-240 | sed 's/^/      /'; FAILED=1; fi
done
echo
if [ "$FAILED" = 0 ]; then printf "%s全部通過%s\n" "$GREEN" "$OFF"; else printf "%s有測試組失敗%s\n" "$RED" "$OFF"; fi
exit "$FAILED"
