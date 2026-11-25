#!/usr/bin/env bash
# 畫面測試：另起一套用完即丟的環境（獨立資料庫與文件 volume、隨機密鑰、只有合成資料），
# 用無頭 Chromium（Playwright）實際操作畫面，結束時整套刪除。正式的資料庫與容器完全不動。
#
#   scripts/run_ui_test.sh            執行（截圖放在 qa/ui/out/）
#   PHASES="A H" scripts/run_ui_test.sh   只跑列出的階段（除錯用；階段之間有先後依賴，要從 A 開始）
#   預設全部：A H R B0 B K C D E F G P1 P2，加上 Oversea（O）、舊案（L）、Accounting 載入失敗（X）、伺服器分頁（Y）等專項、主資料重新啟用（M）與帳號操作（U）
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

# Preserve prior screenshots rather than deleting another run's output.
if [ -e qa/ui/out ]; then
  mv qa/ui/out "qa/ui/out.previous-$(date +%Y%m%d-%H%M%S)-$$" || exit 1
fi
mkdir -p qa/ui/out
run_phase() {
  case " ${PHASES:-A PR CG H R B0 B K C D E F G P1 P2 O L X I Y Z} " in *" $1 "*) ;; *) return 0 ;; esac
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 ui_test.py "$1"
}
STATUS=0
run_phase A || STATUS=1
run_phase PR || STATUS=1
run_phase CL || STATUS=1
# 提醒信採不寄信模式；測試資料的 AE 已關聯 Personnel，確認聯絡資料完整並檢查提醒畫面。
reminders() { docker exec ri-ut-backend python manage.py "$1"; echo; }
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" H "*|*" R "*)
  reminders run_signed_slip_reminders >/dev/null
  docker exec ri-ut-backend python manage.py shell -c "
from personnel.models import Personnel
Personnel.objects.update_or_create(name='UI AE One', department='reinsurance', defaults={'role_code':'sales', 'email':'ui.ae@tw-insure.com', 'supervisor_name':'UI Boss',
                         'supervisor_email':'ui.boss@tw-insure.com', 'created_by':'seed', 'updated_by':'seed'})
Personnel.objects.filter(name='UI Finance').update(email='ui.fin@tw-insure.com'); print('reminder contacts seeded')" 2>&1 | grep seeded
esac
run_phase H || STATUS=1
# 階段 H：每次 Word 下載都記錄 Audit，PDF 引擎已退役。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" H "*)
docker exec ri-ut-backend python manage.py shell -c "
from audit.models import AuditLog
q = AuditLog.objects.filter(action='generate_document')
got = sorted((a.metadata['kind'], a.metadata['format']) for a in q)
want = sorted([('cover','docx'),('debit','docx')])   # 2026-10-28：Draft 批單的 Endorsement Word 要 Announce 後才能下載
print('PASS audit: one generate_document event per download' if got == want else f'FAIL audit events {got}')" > "$UT_SECRETS/audit.txt" 2>&1
grep -E 'PASS|FAIL' "$UT_SECRETS/audit.txt"; grep -q '^PASS' "$UT_SECRETS/audit.txt" || STATUS=1
esac
# 畫面上要到 Production close 才會變成 Confirmed（尚未移植）：在測試環境直接把案件設成 Confirmed，才能測 Reverse／Renewal／修正
docker exec ri-ut-backend python manage.py shell -c "from cases.models import Case; print('confirmed', Case.objects.filter(tw_ref='TWPAR2603001').update(status='closed'))" 2>&1 | grep confirmed

case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" R "*)
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
case " ${PHASES:-A PR CG H R B0 B K C D E F G P1 P2 O L X I Y Z} " in *" CG "*)
  docker exec ri-ut-backend python manage.py shell -c "from masterdata.models import MasterRecord; MasterRecord.objects.get_or_create(entity_type='class', name='Commercial General Liability', defaults={'code':'GL','payload':{},'created_by':'seed','updated_by':'seed'}); print('CGL coverage fixture ready')" || STATUS=1
  run_phase CG || STATUS=1
esac
run_phase C || STATUS=1
run_phase E || STATUS=1
# Production Report：下個月（台北時間）的 USD 匯率先放好，階段 F 才能在下個月產生與關帳
docker exec ri-ut-backend python manage.py shell -c "
import datetime as dt
from fxrates.models import FxRate
t = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
FxRate.objects.create(year_month=f'{y:04d}-{m:02d}', currency='USD', rate='31.2', created_by='seed', updated_by='seed'); print('next-month fx seeded')" 2>&1 | grep seeded
# The main policy fixture in phase A starts in March 2026. Production uses
# inception month even when Announce happened later (2026-11-05 owner rule).
docker exec ri-ut-backend python manage.py shell -c "
from fxrates.models import FxRate
for ym in ('2026-11','2026-12'):   # Production start month 2026-11 and the month after (2026-11-15 rule)
 FxRate.objects.get_or_create(year_month=ym,currency='USD',defaults={'rate':'31.2','created_by':'seed','updated_by':'seed'})
print('inception-month FX seeded')" 2>&1 | grep seeded
run_phase F || STATUS=1
# 階段 D（Accounting）要在 Production close 產生保費交易之後
run_phase D || STATUS=1
run_phase G || STATUS=1
# 忘記密碼（階段 P1／P2）：打開測試環境的寄信（寫成檔案），P1 在畫面申請，腳本從信件取出連結，P2 打開連結設定新密碼
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" P1 "*)
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
# O: Overseas brokerage uses its own six-field form and cash T3 dates.
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" O "*)
  docker exec -i ri-ut-backend python manage.py shell < qa/ui/oversea_business_seed.py || STATUS=1
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 oversea_business.py || STATUS=1
esac
# L: Legacy Data (Old Register) 新增批單／理賠與 Accounting（2026-11-10 起併入完整執行）。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" L "*)
  docker exec -i ri-ut-backend python manage.py shell < qa/ui/legacy_entry_seed.py 2>&1 | grep -v -i "imported auto" || STATUS=1
  run_phase L || STATUS=1
esac
# X: Accounting 載入失敗時顯示常駐錯誤與 Retry（2026-11-10；模擬伺服器 502，不改資料）。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" X "*)
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 accounting_load_error.py || STATUS=1
esac
# DI: Dashboard 互動層（2026-11-25；以假的 /api/dashboard 回應驗證版面、數字格式、Retention 評價邊界與柱狀圖互動，不改資料）。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U DI GI} " in *" DI "*)
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 dashboard_interaction_ui.py || STATUS=1
esac
# GI: 全站互動層第二輪（2026-11-25；側欄滑動底色、按鈕漣漪、必填欄位抖動；不改資料）。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U DI GI} " in *" GI "*)
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 interaction_global_ui.py || STATUS=1
esac
# I: Legacy 網頁匯入（2026-11-11；系統管理員上傳 Register → 預覽 → 匯入 → Accounting）。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" I "*)
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 legacy_import_ui.py || STATUS=1
esac
# Y: Accounting 伺服器分頁（2026-11-17；取代 11-13 的背景合併）——All Accounts／Settled/Closed／Brokerage 每頁 100 列由伺服器篩選排序，
#    先準備 160 筆合成的已結清舊資料歷史（需在 L、I 之後）。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" Y "*)
  docker exec -i ri-ut-backend python manage.py shell < qa/ui/accounting_paging_seed.py 2>&1 | grep -v -i "imported auto" || STATUS=1
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 accounting_history_ui.py || STATUS=1
esac
# Z: 前端拆檔與 Word 產生程式快取（2026-11-13；頁面按需載入、頁面檔失效時自動重新載入、快取標頭）。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" Z "*)
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 frontend_chunks_ui.py || STATUS=1
esac
# M: Master Data 重新啟用（2026-11-16）：儲存內容不變時直接啟用；畫面補上市場資料而會一併改變內容時，跳出填理由視窗。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" M "*)
  docker exec -i ri-ut-backend python manage.py shell < qa/ui/mdm_reactivate_seed.py 2>&1 | grep -v -i "imported auto" || STATUS=1
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 mdm_reactivate_ui.py || STATUS=1
  result=$(docker exec ri-ut-backend python manage.py shell -c "
from audit.models import EntitySnapshot
from masterdata.models import MasterRecord
r=MasterRecord.objects.get(entity_type='reinsurer', name=\"Lloyd's Underwriter Syndicate No. 9901 UIR\")
s=EntitySnapshot.objects.filter(entity_type='master_record', entity_id=str(r.pk)).order_by('-entity_version').first()
ok=r.is_active and s is not None and s.snapshot_data.get('changeReason')=='UI reactivation reason'
print('PASS the reactivation reason is kept in the version snapshot' if ok else 'FAIL reactivation reason not in snapshot')
" 2>&1 | grep -E '^(PASS|FAIL)')
  echo "$result"; [[ "$result" == PASS* ]] || STATUS=1
esac
# U: 人員頁的帳號操作（2026-11-17；四個帳號網址合為一個，以 action 區分）——重設密碼、停用、重新啟用。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U} " in *" U "*)
  docker exec -i ri-ut-backend python manage.py shell < qa/ui/personnel_accounts_seed.py 2>&1 | grep -v -i "imported auto" || STATUS=1
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 personnel_accounts_ui.py || STATUS=1
esac
# V：Reinsurance Staff 審核應付給 Swiss Re Asia／Allianz（Facility）的帳款、只能取消自己的審核（2026-11-19）。
case " ${PHASES:-A H R B0 B K C D E F G P1 P2 O L X I Y Z M U V} " in *" V "*)
  docker exec -i ri-ut-backend python manage.py shell < qa/ui/facility_review_seed.py 2>&1 | grep -v -i "imported auto" || STATUS=1
  docker run --rm --network ri-uitest_ut --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/qa/ui:/ui" -w /ui ri-ui-playwright:1.56.0 python3 facility_review_ui.py || STATUS=1
esac
exit $STATUS
