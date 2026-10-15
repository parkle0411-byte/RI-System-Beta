#!/usr/bin/env bash
# 畫面測試：另起一套用完即丟的環境（獨立資料庫與文件 volume、隨機密鑰、只有合成資料），
# 用無頭 Chromium（Playwright）實際操作畫面，結束時整套刪除。正式的資料庫與容器完全不動。
#
#   scripts/run_ui_test.sh            執行（截圖放在 qa/ui/out/）
#   PHASES="A H" scripts/run_ui_test.sh   只跑列出的階段（除錯用；階段之間有先後依賴，要從 A 開始）
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
  case " ${PHASES:-A H R B0 B K C D E F G P1 P2} " in *" $1 "*) ;; *) return 0 ;; esac
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 ui_test.py "$1"
}
STATUS=0
run_phase A || STATUS=1
# 提醒信（不寄信模式）：先在 AE 沒有人員資料時跑一次（設定錯誤），補上 AE／主管／Finance 的 e-mail 後再跑（Suppressed），階段 R 在畫面上檢查。
# 2026-10-13 起產生 Word 文件需要 AE 的 Email（由 Personnel 依姓名帶入），所以「設定錯誤」那一次提醒先在階段 H 之前跑，再補上聯絡資料。
reminders() { docker exec ri-ut-backend python manage.py "$1"; echo; }
case " ${PHASES:-A H R B0 B K C D E F G P1 P2} " in *" H "*|*" R "*)
  reminders run_signed_slip_reminders >/dev/null
  docker exec ri-ut-backend python manage.py shell -c "
from personnel.models import Personnel
Personnel.objects.create(name='UI AE One', department='reinsurance', role_code='sales', email='ui.ae@tw-insure.com', supervisor_name='UI Boss',
                         supervisor_email='ui.boss@tw-insure.com', created_by='seed', updated_by='seed')
Personnel.objects.filter(name='UI Finance').update(email='ui.fin@tw-insure.com'); print('reminder contacts seeded')" 2>&1 | grep seeded
esac
run_phase H || STATUS=1
# 階段 H：每次 Word 下載都記錄 Audit，PDF 引擎已退役。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2} " in *" H "*)
docker exec ri-ut-backend python manage.py shell -c "
from audit.models import AuditLog
q = AuditLog.objects.filter(action='generate_document')
got = sorted((a.metadata['kind'], a.metadata['format']) for a in q)
want = sorted([('cover','docx'),('debit','docx'),('endorsement','docx')])
print('PASS audit: one generate_document event per download' if got == want else f'FAIL audit events {got}')" > "$UT_SECRETS/audit.txt" 2>&1
grep -E 'PASS|FAIL' "$UT_SECRETS/audit.txt"; grep -q '^PASS' "$UT_SECRETS/audit.txt" || STATUS=1
esac
# 畫面上要到 Production close 才會變成 Confirmed（尚未移植）：在測試環境直接把案件設成 Confirmed，才能測 Reverse／Renewal／修正
docker exec ri-ut-backend python manage.py shell -c "from cases.models import Case; print('confirmed', Case.objects.filter(tw_ref='TWPAR2603001').update(status='closed'))" 2>&1 | grep confirmed

case " ${PHASES:-A H R B0 B K C D E F G P1 P2} " in *" R "*)
  echo "signed slip: $(reminders run_signed_slip_reminders)"
  echo "payment:     $(reminders run_payment_reminders)"
esac
run_phase R || STATUS=1
run_phase B0 || STATUS=1   # 批單 Draft 還在時：續保被擋，畫面要說明原因
# 階段 A 留下一張批單 Draft；有未完成批單時續保被擋（要從最新且全部已確認的鏈建立），所以先把它丟進回收（模擬業務員放棄這張批單 Draft）
docker exec ri-ut-backend python manage.py shell -c "
from django.utils import timezone
from cases.models import Case
print('endorsement draft discarded', Case.objects.filter(parent_case__tw_ref='TWPAR2603001', status='draft').update(recycled_at=timezone.now(), recycled_by='seed'))" 2>&1 | grep discarded
run_phase B || STATUS=1
run_phase K || STATUS=1
run_phase C || STATUS=1
run_phase E || STATUS=1
# Production Report：下個月（台北時間）的 USD 匯率先放好，階段 F 才能在下個月產生與關帳
docker exec ri-ut-backend python manage.py shell -c "
import datetime as dt
from fxrates.models import FxRate
t = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
FxRate.objects.create(year_month=f'{y:04d}-{m:02d}', currency='USD', rate='31.2', created_by='seed', updated_by='seed'); print('next-month fx seeded')" 2>&1 | grep seeded
run_phase F || STATUS=1
# 階段 D（Accounting）要在 Production close 產生保費交易之後
run_phase D || STATUS=1
run_phase G || STATUS=1
# 忘記密碼（階段 P1／P2）：打開測試環境的寄信（寫成檔案），P1 在畫面申請，腳本從信件取出連結，P2 打開連結設定新密碼
case " ${PHASES:-A H R B0 B K C D E F G P1 P2} " in *" P1 "*)
  UT_EMAIL_ENABLED=true "${COMPOSE[@]}" up -d backend >/dev/null 2>&1
  for i in $(seq 1 30); do docker exec ri-ut-backend python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/auth/password-reset')" >/dev/null 2>&1 && break; sleep 1; done
  docker exec ri-ut-backend python manage.py shell -c "
from personnel.models import Personnel
Personnel.objects.filter(name='UI Sales').update(email='ui.sales@tw-insure.com'); print('reset e-mail seeded')" 2>&1 | grep seeded
  run_phase P1 || STATUS=1
  docker exec ri-ut-backend python -c "
import email, glob, os, re
files = sorted(glob.glob('/tmp/ri-mail/*'), key=os.path.getmtime)
msg = email.message_from_bytes(open(files[-1], 'rb').read())
text = next(p for p in msg.walk() if p.get_content_type() == 'text/plain').get_payload(decode=True).decode('utf-8')
print(msg['To']); print(re.search(r'http://nginx/reset-password\\?uid=\\S+', text).group())" > "$UT_SECRETS/reset.txt" 2>&1
  head -1 "$UT_SECRETS/reset.txt" | grep -q 'ui.sales@tw-insure.com' && echo "PASS reset e-mail sent to ui.sales@tw-insure.com" || { echo "FAIL reset e-mail: $(cat "$UT_SECRETS/reset.txt")"; STATUS=1; }
  sed -n 2p "$UT_SECRETS/reset.txt" > qa/ui/out/reset-link.txt
  run_phase P2 || STATUS=1
esac
exit $STATUS
