#!/usr/bin/env bash
# 一鍵執行全部驗證。每次改動後都應該跑一次；有任何一項失敗就以非 0 結束。
#
#   scripts/run_qa.sh            全部
#   scripts/run_qa.sh suites     只跑資料庫／API 測試組
#   scripts/run_qa.sh parity     只跑「前後端密碼規則一致」
#   scripts/run_qa.sh totals     只跑「畫面上的案件合計（前端 JS）與後端 totals.py 一致」
#   scripts/run_qa.sh pages      只跑「Accounting 伺服器分頁與畫面原本的篩選／排序逐頁一致」（正式資料，唯讀；約 3 分鐘）
#                                PAGES_BACKEND=<容器> 改用其他後端容器（例如壓測環境 ri-stress-backend）
#
# 所有測試組都在交易內執行、最後回滾，不會在資料庫留下任何測試資料，也不依賴真實人員或案件資料
# （需要的人員由測試自己建立）。需要 ri-backend 容器正在執行。
set -uo pipefail
cd "$(dirname "$0")/.."
WHAT="${1:-all}"
FAILED=0
GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'

ok()   { printf "  %s%s%s\n" "$GREEN" "$1" "$OFF"; }
bad()  { printf "  %s%s%s\n" "$RED" "$1" "$OFF"; FAILED=1; }

run_suites() {
  echo "== 資料庫／API 測試組 =="
  for f in backend/qa/suites/*.py; do
    name=$(basename "$f" .py)
    out=$(docker exec -i ri-backend python manage.py shell < "$f" 2>&1 | grep -v -i "warn\|imported auto")
    line=$(grep -E "passed" <<<"$out" | head -1)
    if [ -n "$line" ] && ! grep -q "^FAIL" <<<"$out"; then ok "$(printf '%-28s' "$name") $line"
    else bad "$(printf '%-28s' "$name") 失敗"; grep -E "^FAIL|Traceback|Error" <<<"$out" | head -8 | sed 's/^/      /'; fi
  done
}

run_parity() {
  echo "== 前端與後端的密碼規則是否一致 =="
  b=$(docker exec -i ri-backend python manage.py shell < backend/qa/password_rule_backend.py 2>&1 | grep '^RESULT ' | sed 's/^RESULT //')
  f=$(docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/frontend/src:/src:ro" -v "$PWD/backend/qa:/qa:ro" node:22-alpine node /qa/password_rule_frontend.mjs 2>&1)
  # 比對內容，不比對字串（JavaScript 會把「像數字的鍵」排到前面，順序不同不代表內容不同）
  res=$(python3 - "$b" "$f" <<'PY'
import json, sys
try:
    b, f = json.loads(sys.argv[1]), json.loads(sys.argv[2])
except Exception as e:
    print("ERROR", e); raise SystemExit
diff = [k for k in set(b) | set(f) if b.get(k) != f.get(k)]
print(("OK %d" % len(b)) if not diff and b else "DIFF " + json.dumps(diff, ensure_ascii=False))
PY
)
  case "$res" in
    OK*) ok "後端與前端對 ${res#OK } 組密碼的判斷完全一致" ;;
    *)   bad "前後端判斷不一致（或執行失敗）: $res" ;;
  esac
}

run_totals() {
  echo "== 案件合計：前端畫面（caseCalculations.js）與後端（totals.py）是否一致 =="
  res=$(docker exec ri-backend python -m qa.frontend_totals_vectors 3000 \
    | docker run --rm -i --user "$(id -u):$(id -g)" -v "$PWD/frontend/src:/src:ro" -v "$PWD/backend/qa:/qa:ro" node:22-alpine node /qa/frontend_totals.mjs 2>&1)
  total=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["total"] if d["bad"] == 0 else "BAD " + json.dumps(d, ensure_ascii=False)[:600])' "$res" 2>&1)
  case "$total" in
    BAD*|*Error*|*rror*) bad "前後端合計不一致（或執行失敗）: $total" ;;
    *) ok "前端與後端對 ${total} 個案件的合計（十個欄位）完全一致" ;;
  esac
}

run_pages() {
  echo "== Accounting 伺服器分頁：與畫面原本的程式（accountingRows.js、accountingList.js）逐頁比對 =="
  out=$(mktemp); trap 'rm -f "$out"' RETURN
  docker exec -i "${PAGES_BACKEND:-ri-backend}" python manage.py shell < backend/qa/accounting_pages_backend.py 2>/dev/null > "$out"
  res=$(docker run --rm -i --user "$(id -u):$(id -g)" -v "$PWD/frontend/src:/src:ro" -v "$PWD/backend/qa:/qa:ro" node:22-alpine \
        node --max-old-space-size=4096 /qa/accounting_pages_frontend.mjs < "$out" 2>&1)
  line=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print("%d 列、%d 種條件、%d 頁、%d 列逐列比對" % (d["rows"], d["checks"], d["pagesCompared"], d["rowsCompared"]) if d["problems"] == 0 else "BAD " + json.dumps(d, ensure_ascii=False)[:800])' "$res" 2>&1)
  case "$line" in
    BAD*|*rror*) bad "伺服器分頁與畫面程式不一致（或執行失敗）: $line" ;;
    *) ok "伺服器分頁與畫面程式完全一致：$line" ;;
  esac
}

case "$WHAT" in
  suites) run_suites ;;
  parity) run_parity ;;
  totals) run_totals ;;
  pages)  run_pages ;;
  all)    run_suites; run_parity; run_totals; run_pages ;;
  *) echo "用法: $0 [all|suites|parity|totals]"; exit 2 ;;
esac

echo
if [ "$FAILED" = 0 ]; then printf "%s全部通過%s\n" "$GREEN" "$OFF"; else printf "%s有項目失敗%s\n" "$RED" "$OFF"; fi
exit "$FAILED"
