#!/usr/bin/env bash
# 用某組設定重建後端／MySQL（資料沿用），依序量：單人、7 人同時開 Accounting、（可選）7 人平常使用。
#   matrix.sh 名稱 worker數 thread數 緩衝區MB [mixed]
cd "$(dirname "$0")/../.."
NAME=$1; export STRESS_WORKERS=$2 STRESS_THREADS=$3 STRESS_BP=$(( $4 * 1048576 )); MIXED=${5:-}
export STRESS_SECRETS="${STRESS_SECRETS:-/tmp/ri-stress-secrets}" STRESS_OUT="${STRESS_OUT:-/tmp/ri-stress-out}"
OUT="$STRESS_OUT/matrix/$NAME"; mkdir -p "$OUT"; rm -f "$OUT"/*
echo "=== $NAME: workers=$2 threads=$3 buffer_pool=${4}MB $(date +%T) ==="
docker compose -f qa/stress/compose.yaml up -d --force-recreate --wait mysql backend >/dev/null 2>&1 || { echo "啟動失敗"; exit 1; }
for i in $(seq 1 60); do docker exec ri-stress-backend python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health/',timeout=5)" >/dev/null 2>&1 && break; sleep 2; done
docker exec ri-stress-mysql sh -c 'mysql -uroot -p"$(cat /run/secrets/mysql_root_password)" -N -e "SELECT CONCAT(\"buffer_pool_mb=\", @@innodb_buffer_pool_size/1048576)" 2>&1 | grep -v "Using a password"'
( while true; do free -m | awk '/Mem/{print $7}' >> "$OUT/host_available_mb.txt"; sleep 3; done ) & FREEPID=$!
qa/stress/monitor.sh start "$OUT/mon.csv"
qa/stress/load.sh single /api/accounting /api/dashboard "/api/production-report?month=2026-09" /api/cases --reps 2 > "$OUT/single.txt" 2>&1
sleep 65
qa/stress/load.sh burst /api/accounting --rounds 2 > "$OUT/burst_accounting.txt" 2>&1
if [ "$MIXED" = mixed ]; then
  sleep 65
  qa/stress/load.sh mixed --minutes 6 --think 5,20 > "$OUT/mixed.txt" 2>&1
fi
qa/stress/monitor.sh stop "$OUT/mon.csv"; kill $FREEPID 2>/dev/null
{ qa/stress/monitor.sh summary "$OUT/mon.csv"
  echo "  主機可用記憶體最低: $(sort -n "$OUT/host_available_mb.txt" | head -1) MB"
  echo "  後端 OOMKilled=$(docker inspect ri-stress-backend --format '{{.State.OOMKilled}}')  重啟次數=$(docker inspect ri-stress-backend --format '{{.RestartCount}}')"
  echo "  gunicorn 異常紀錄: $(docker logs ri-stress-backend 2>&1 | grep -ci 'timeout\|killed\|SIGKILL')"; } > "$OUT/resources.txt"
echo "完成 $NAME $(date +%T)"
