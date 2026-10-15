#!/usr/bin/env bash
# 在壓測環境的網路內執行負載產生器：qa/stress/load.sh baseline|single|burst|mixed|sustained [參數]
cd "$(dirname "$0")/../.."
OUT="${STRESS_OUT:-/tmp/ri-stress-out}"; mkdir -p "$OUT"
# 後端容器重建後 /tmp 會清空；沒有範例清單就從資料庫重新產生
docker exec ri-stress-backend test -s /tmp/stress_samples.json || docker exec -i ri-stress-backend python manage.py shell < qa/stress/samples.py >/dev/null 2>&1
docker cp ri-stress-backend:/tmp/stress_samples.json "$OUT/samples.json" >/dev/null
exec docker run --rm -u 1001:1001 --network ri-stress_stress -v "$OUT/samples.json:/samples.json:ro" \
  -v "$PWD/qa/stress/load.py:/load.py:ro" ri-backend:stress python -u /load.py "$@"
