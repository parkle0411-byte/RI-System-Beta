#!/usr/bin/env bash
# 切換演練（只用合成資料；不碰 Alpha、不碰 VM 正式資料庫）：
#   A：一套用完即丟的環境扮演 Alpha，用 API 建出各種情境 → 擷取各畫面 API 輸出 → 匯出成 Alpha 格式
#   B：另一套全新的環境，先把人員／主檔／案件的流水號推到別的數字（確保 ID 一定不同）→
#      先餵幾份壞掉的匯出檔確認會被擋下 → dry-run → 正式匯入 → 再匯入一次應被拒絕 →
#      擷取同樣的 API 輸出，與 A 逐項比對（ID 各自換成 case_uid／人員姓名）→ 在 B 關掉 A 留下的 valid 報表
set -uo pipefail
cd "$(dirname "$0")/../.."
UT_SECRETS="$(mktemp -d)"; export UT_SECRETS
WORK="$(mktemp -d)"
COMPOSE=(docker compose -f qa/ui/compose.uitest.yaml)
cleanup() { "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1; rm -rf "$UT_SECRETS"; [ "${KEEP:-0}" = 1 ] || rm -rf "$WORK"; }
trap cleanup EXIT
for s in mysql_root_password mysql_app_password django_secret_key; do head -c 32 /dev/urandom | base64 | tr -d '/+=\n' > "$UT_SECRETS/$s"; done
chmod 644 "$UT_SECRETS"/*
STATUS=0
fail() { echo "  FAIL $*"; STATUS=1; }
pass() { echo "  PASS $*"; }
sql() { docker exec -i ri-ut-mysql sh -c 'mysql -uroot -p"$(cat /run/secrets/mysql_root_password)" ri_system 2>/dev/null'; }
shell() { docker exec -i ri-ut-backend python manage.py shell 2>&1 | grep -v "objects imported"; }
up() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1
  "${COMPOSE[@]}" up -d --wait >/dev/null 2>&1 || { echo "stack failed"; exit 1; }
  for i in $(seq 1 60); do docker exec ri-ut-backend python manage.py migrate -v 0 >/dev/null 2>&1 && break; sleep 2; done
  docker exec ri-ut-backend mkdir -p /tmp/rehearsal
  for f in common.py scenario.py capture.py; do docker cp "qa/conversion/$f" ri-ut-backend:/tmp/rehearsal/ >/dev/null; done
}
imp() { docker exec ri-ut-backend python manage.py import_alpha_cutover "/tmp/rehearsal/$1" --files "/tmp/rehearsal/$2" ${3:-} 2>&1; }

if [ -n "${REUSE_WORK:-}" ]; then   # 重用上一次 A 的擷取與匯出（改壞測試用），只跑 B
  rm -rf "$WORK"; WORK="$REUSE_WORK"; KEEP=1
else
echo "== A: build the Alpha stand-in =="
up
shell < qa/ui/seed.py >/dev/null
shell < qa/conversion/scenario.py | tail -1
shell < qa/conversion/capture.py > "$WORK/a.json"
docker exec ri-ut-backend python manage.py export_alpha_shape /tmp/rehearsal/export.json --files /tmp/rehearsal/files | tail -1
docker cp ri-ut-backend:/tmp/rehearsal/export.json "$WORK/export.json" >/dev/null
docker cp ri-ut-backend:/tmp/rehearsal/files "$WORK/files" >/dev/null
fi

echo "== B: fresh VM with different IDs =="
up
[ -n "${MUTATE:-}" ] && docker cp "${MUTATE%%:*}" "ri-ut-backend:/app/${MUTATE##*:}" >/dev/null   # 改壞測試：換上被改壞的檔案
echo "ALTER TABLE ri_personnel AUTO_INCREMENT = 300; ALTER TABLE ri_master_records AUTO_INCREMENT = 200; ALTER TABLE ri_cases AUTO_INCREMENT = 1000;" | sql
shell < qa/ui/seed.py >/dev/null
echo "from masterdata.models import MasterRecord; MasterRecord.objects.create(entity_type='foreign_broker', name='UI VM-only Broker', payload={}, created_by='seed', updated_by='seed')" | shell
rm -rf "$WORK/files-corrupt" "$WORK/files-missing"
python3 - "$WORK" <<'PY'
import json, sys, shutil, pathlib
w = pathlib.Path(sys.argv[1]); e = json.loads((w / "export.json").read_text())
bad = json.loads(json.dumps(e)); m = next(r for r in bad["tables"]["ri_master_records"] if r["name"] == "UI Re Alpha")
m["payload"] = {**(m["payload"] or {}), "ratings": [{"agency": "S&P", "rating": "AA-"}]}
(w / "conflict.json").write_text(json.dumps(bad))
shutil.copytree(w / "files", w / "files-corrupt"); f = next(p for p in (w / "files-corrupt").rglob("*") if p.is_file()); f.write_bytes(f.read_bytes() + b"x")
shutil.copytree(w / "files", w / "files-missing"); next(p for p in (w / "files-missing").rglob("*") if p.is_file()).unlink()
PY
for f in export.json conflict.json files files-corrupt files-missing; do docker cp "$WORK/$f" ri-ut-backend:/tmp/rehearsal/ >/dev/null; done

out=$(imp conflict.json files); echo "$out" | grep -q '"reference_conflict"' && echo "$out" | grep -q "UI Re Alpha" && pass "changed master content -> stops with reference_conflict naming it" || { fail "conflict not detected"; echo "$out" | tail -5; }
out=$(imp export.json files-corrupt); echo "$out" | grep -q '"document_problem"' && echo "$out" | grep -q "SHA-256" && pass "tampered file -> stops (SHA-256)" || fail "tampered file not detected"
out=$(imp export.json files-missing); echo "$out" | grep -q "is missing from the export" && pass "missing file -> stops" || fail "missing file not detected"
out=$(imp export.json files); echo "$out" | grep -q "DRY-RUN (rolled back)" && echo "$out" | grep -q "reconciliation: OK" && pass "dry-run reconciles" || { fail "dry-run"; echo "$out" | tail -20; }
n=$(echo "from cases.models import Case; print('N', Case.objects.count())" | shell | grep '^N'); [ "$n" = "N 0" ] && pass "dry-run left no cases behind" || fail "dry-run left data: $n"
out=$(imp export.json files --apply); echo "$out" | grep -q "(committed)" && pass "apply committed" || { fail "apply"; echo "$out" | tail -20; }
echo "$out" | sed -n '/==/,$p'
out=$(imp export.json files --apply); echo "$out" | grep -q '"target_not_empty"' && pass "second apply refused (target_not_empty)" || fail "second apply not refused"

shell < qa/conversion/capture.py > "$WORK/b.json"
python3 qa/conversion/compare.py "$WORK/a.json" "$WORK/b.json" && pass "every screen API output identical between A and B" || fail "outputs differ"
echo "from cases.models import Case; print('IDS', min(Case.objects.values_list('pk', flat=True)) >= 1000)" | shell | grep -q "IDS True" && pass "B really used different case IDs (all >= 1000)" || fail "IDs not shifted"

# 切換後繼續作業：關掉 A 留下的下月 valid 報表（簽章與 key 都必須已正確換成 B 的 ID）
cat > "$WORK/close.py" <<'PY'
import sys; sys.path.insert(0, "/tmp/rehearsal")
from common import call, login, months
from cases.models import Case
M1, M2 = months(); admin = login("ui.admin")
j = call(admin, "get", f"/api/production-report?month={M2}").json()
latest = j["versions"][0]
print("CANCLOSE", j["scope"]["canCloseLatest"], latest["status"])
r = call(admin, "post", "/api/production-report", {"action": "close", "month": M2, "reportUid": latest["reportUid"], "rowVersion": latest["rowVersion"], "sourceSignature": j["sourceSignature"]})
print("CLOSE", r.status_code, r.json().get("confirmedCases"))
print("STATUS", sorted(c.status for c in Case.objects.filter(payload__originalInsured="Rehearsal Insured", parent_case__isnull=True)))
PY
docker cp "$WORK/close.py" ri-ut-backend:/tmp/rehearsal/ >/dev/null
out=$(shell < "$WORK/close.py")
echo "$out" | grep -q "CANCLOSE True valid" && pass "imported valid report can be closed (signature matches the remapped preview)" || { fail "cannot close imported report"; echo "$out"; }
echo "$out" | grep -q "CLOSE 200" && pass "close after import succeeded: $(echo "$out" | grep CLOSE)" || fail "close failed: $out"
echo "$out" | grep -q "STATUS \['closed', 'closed'\]" && pass "both rehearsal cases fully Confirmed after the deferred and 2nd-installment rows closed" || fail "statuses: $(echo "$out" | grep STATUS)"
cnt=$(echo "from conversion.models import MigrationItem, MigrationBatch; from audit.models import AuditLog; print('CNT', MigrationBatch.objects.filter(status='completed').count(), MigrationItem.objects.filter(status='reconciled').count(), MigrationItem.objects.exclude(status='reconciled').count(), AuditLog.objects.filter(source='data_migration').count())" | shell | grep CNT)
echo "  batch/items/audit: $cnt"
echo "$cnt" | grep -qE "CNT 1 [0-9]+ 0 [0-9]+" && pass "one completed batch, every item reconciled, audit events written" || fail "batch bookkeeping: $cnt"
[ "${KEEP:-0}" = 1 ] && echo "work dir kept: $WORK"
exit $STATUS
