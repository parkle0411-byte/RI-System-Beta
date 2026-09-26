#!/usr/bin/env bash
# 畫面測試：另起一套用完即丟的環境（獨立資料庫與文件 volume、隨機密鑰、只有合成資料），
# 用無頭 Chromium（Playwright）實際操作畫面，結束時整套刪除。正式的資料庫與容器完全不動。
#
#   scripts/run_ui_test.sh            執行（截圖放在 qa/ui/out/）
#   KEEP=1 scripts/run_ui_test.sh     測完先不刪環境（除錯用；之後手動 docker compose -p ri-uitest down -v）
set -uo pipefail
cd "$(dirname "$0")/.."
UT_SECRETS="$(mktemp -d)"; export UT_SECRETS
COMPOSE=(docker compose -f qa/ui/compose.uitest.yaml)
cleanup() {
  if [ "${KEEP:-0}" != "1" ]; then "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1; fi
  rm -rf "$UT_SECRETS"
}
trap cleanup EXIT
for s in mysql_root_password mysql_app_password django_secret_key; do head -c 32 /dev/urandom | base64 | tr -d '/+=\n' > "$UT_SECRETS/$s"; done
chmod 644 "$UT_SECRETS"/*   # 容器內以非 root 讀取（隨機值，測完即刪）

docker build -q -t ri-ui-playwright:1.56.0 -f qa/ui/Dockerfile.playwright qa/ui >/dev/null || { echo "Playwright 映像建置失敗"; exit 1; }
"${COMPOSE[@]}" up -d --wait >/dev/null 2>&1 || { echo "測試環境啟動失敗"; "${COMPOSE[@]}" logs --tail 40; exit 1; }
# MySQL 初始化期間健康檢查就會通過（那是只接受本機連線的暫時伺服器），所以重試到真的連得上
for i in $(seq 1 60); do
  docker exec ri-ut-backend python manage.py migrate -v 0 >/dev/null 2>&1 && break
  [ "$i" = 60 ] && { echo "資料庫一直無法連線"; exit 1; }
  sleep 2
done
docker exec -i ri-ut-backend python manage.py shell < qa/ui/seed.py 2>&1 | grep -v -i "imported auto" || exit 1

rm -rf qa/ui/out && mkdir -p qa/ui/out
run_phase() {
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 ui_test.py "$1"
}
STATUS=0
run_phase A || STATUS=1
# 畫面上要到 Production close 才會變成 Confirmed（尚未移植）：在測試環境直接把案件設成 Confirmed，才能測 Reverse／Renewal／修正
docker exec ri-ut-backend python manage.py shell -c "from cases.models import Case; print('confirmed', Case.objects.filter(tw_ref='TWPAR2603001').update(status='closed'))" 2>&1 | grep confirmed
run_phase B || STATUS=1
run_phase C || STATUS=1
run_phase D || STATUS=1
run_phase E || STATUS=1
# Production Report：下個月（台北時間）的 USD 匯率先放好，階段 F 才能在下個月產生與關帳
docker exec ri-ut-backend python manage.py shell -c "
import datetime as dt
from fxrates.models import FxRate
t = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
FxRate.objects.create(year_month=f'{y:04d}-{m:02d}', currency='USD', rate='31.2', created_by='seed', updated_by='seed'); print('next-month fx seeded')" 2>&1 | grep seeded
run_phase F || STATUS=1
exit $STATUS
