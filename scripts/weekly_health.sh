#!/usr/bin/env bash
# 每週健檢報告（2026-11-13 業主決定）：唯讀，不改任何資料或設定。每週三 Debug 時執行，用來提早發現系統變慢。
#   scripts/weekly_health.sh            印出報告並附加到 logs/weekly-health.log
#   scripts/weekly_health.sh --no-log   只印出
# 內容：主機記憶體／swap／硬碟、容器狀態、Docker 映像與備份數量、最慢的頁面（nginx 的 urt，容器重建後重新累計）、
#       資料量（案件、舊資料、快照）、Accounting 各段回應的大小與時間（在交易內讀取後回復，不寫入）。
set -uo pipefail
cd "$(dirname "$0")/.."
LOG=1; [[ "${1:-}" == "--no-log" ]] && LOG=0
OUT=$(mktemp); trap 'rm -f "$OUT"' EXIT
{
echo "================ RI System weekly health  $(date '+%Y-%m-%d %H:%M %Z') ================"
echo "## 主機"
uptime | sed 's/^ *//'
free -m | awk 'NR==2{printf "記憶體：共 %d MB，可用 %d MB\n",$2,$7} NR==3{printf "swap：已用 %d MB / %d MB%s\n",$3,$2,($3>500?"  ← 偏高，測試後請依 VM-RULES §3 搬回記憶體":"")}'
df -h / | awk 'NR==2{printf "硬碟：已用 %s / %s（%s）\n",$3,$2,$5}'
echo
echo "## 容器"
docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Image}}' | sort | awk -F'\t' '{printf "%-40s %-28s %s\n",$1,$2,$3}'
extra=$(docker ps -a --format '{{.Names}}' | grep -vcE '^ri-(backend|nginx|mysql)$' || true)
[ "$extra" -gt 0 ] && echo "（另有 $extra 個非正式容器：用不到的測試環境請停止或刪除）"
echo
echo "## Docker 與備份"
docker system df --format '{{.Type}}\t{{.TotalCount}}\t{{.Size}}\t{{.Reclaimable}}' | awk -F'\t' '{printf "%-14s 數量 %-5s 大小 %-10s 可回收 %s\n",$1,$2,$3,$4}'
echo "回滾點映像（before-*）：$(docker images --format '{{.Tag}}' | grep -c '^before-' || true) 個標籤"
echo "備份：$(ls backups 2>/dev/null | wc -l) 項，$(du -sh backups 2>/dev/null | cut -f1)；超過 14 天未打包：$(find backups -mindepth 1 -maxdepth 1 -mtime +14 ! -name 'archive_*' ! -name 'work-folders_*' 2>/dev/null | wc -l) 項"
echo
echo "## 最慢的頁面（nginx 記錄的後端處理時間 urt；自 ri-nginx 上次啟動 $(date -d "$(docker inspect -f '{{.State.StartedAt}}' ri-nginx 2>/dev/null)" '+%m-%d %H:%M' 2>/dev/null) 起）"
docker logs ri-nginx 2>/dev/null | python3 -I -c '
import re, sys, collections
stats = collections.defaultdict(list)
for line in sys.stdin:
    m = re.search(r"\"(GET|POST|PUT|PATCH|DELETE) (\S+) HTTP/[\d.]+\" (\d{3}) .* urt=([\d.]+)", line)
    if not m: continue
    path = m.group(2).split("?")[0]
    if not path.startswith("/api/"): continue
    query = m.group(2).partition("?")[2]
    if path == "/api/accounting" and m.group(1) == "GET":
        path += " [history]" if "legacy=history" in query else " [open]" if "legacy=open" in query else " [full]"
    stats[(m.group(1), path)].append(float(m.group(4)))
if not stats:
    print("（沒有紀錄：容器剛重建，或這段期間沒有人使用）")
rows = sorted(stats.items(), key=lambda kv: -max(kv[1]))[:10]
if rows: print("%-7s %-46s %6s %8s %8s %8s" % ("方法", "網址", "次數", "平均秒", "最慢秒", "超過2秒"))
for (method, path), v in rows:
    print("%-7s %-46s %6d %8.2f %8.2f %8d" % (method, path, len(v), sum(v) / len(v), max(v), sum(1 for x in v if x > 2)))
total = sum(len(v) for v in stats.values()); slow = sum(1 for v in stats.values() for x in v if x > 2)
if total: print("API 請求共 %d 次，其中超過 2 秒 %d 次（%.1f%%）" % (total, slow, 100.0 * slow / total))
'
echo
echo "## 資料量與 Accounting 回應"
docker exec -i ri-backend python manage.py shell 2>/dev/null <<'PY' | sed -n '/^HEALTH-BEGIN$/,/^HEALTH-END$/p' | grep -v '^HEALTH-'
import time
from django.db import connection, transaction
from django.db.models import Count
from django.test import RequestFactory
from django.urls import resolve
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.signed_cookies import SessionStore
from cases.models import Case
from legacy.models import LegacyTransaction
from personnel.models import Personnel
print('HEALTH-BEGIN')
by = {(r['status']): r['n'] for r in Case.objects.values('status').annotate(n=Count('id'))}
print('案件：共 %d 件（%s）' % (Case.objects.count(), '、'.join(f'{k} {v}' for k, v in sorted(by.items())) or '無'))
confirmed = LegacyTransaction.objects.filter(status='confirmed')
print('舊資料交易：已確認 %d 筆（已結清歷史 %d、未結清或新增 %d），草稿 %d 筆' % (confirmed.count(), confirmed.filter(historical=True).count(),
      confirmed.filter(historical=False).count(), LegacyTransaction.objects.filter(status='draft').count()))
with connection.cursor() as c:
    c.execute("SELECT ROUND(SUM(data_length+index_length)/1024/1024,1) FROM information_schema.tables WHERE table_schema=DATABASE()")
    size = c.fetchone()[0]
    c.execute("SELECT table_name, ROUND((data_length+index_length)/1024/1024,1) FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY (data_length+index_length) DESC LIMIT 3")
    top = c.fetchall()
print('資料庫大小：%s MB（最大的表：%s）' % (size, '、'.join(f'{n} {s} MB' for n, s in top)))
person = (Personnel.objects.filter(role_code__in=('accounting_manager', 'accounting', 'admin'), is_active=True, account_status='active')
          .exclude(auth_user_id=None).order_by('id').first())
if person is None:
    print('Accounting 回應：沒有可用的財會／管理員帳號，略過')
else:
    user = get_user_model().objects.get(pk=person.auth_user_id); rf = RequestFactory(HTTP_HOST='localhost')
    for label, url in (('打開時（不含已結清舊資料歷史）', '/api/accounting?view=list&legacy=open'),
                       ('背景載入的舊資料歷史', '/api/accounting?view=list&legacy=history'), ('完整清單', '/api/accounting?view=list')):
        try:
            m = resolve('/api/accounting'); req = rf.get(url); req.user = user; req.session = SessionStore()
            started = time.perf_counter()
            with transaction.atomic():
                r = m.func(req); r.render(); transaction.set_rollback(True)
            print('Accounting %s：%.2f 秒，%.1f MB（HTTP %d）' % (label, time.perf_counter() - started, len(r.content) / 1048576, r.status_code))
        except Exception as exc:
            print('Accounting %s：無法量測（%s）' % (label, type(exc).__name__))
print('HEALTH-END')
PY
echo "=================================================================================="
} > "$OUT" 2>&1
cat "$OUT"
if [ "$LOG" = 1 ]; then mkdir -p logs; cat "$OUT" >> logs/weekly-health.log; echo; echo "（已附加到 logs/weekly-health.log）"; fi
