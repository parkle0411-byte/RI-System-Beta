#!/usr/bin/env bash
# 資料庫防護：建立網站平常使用的 ri_runtime 帳號、設定最小權限、建立 Audit 的不可變 trigger。
#
# 為什麼需要：
#   ri_app 對整個資料庫有全部權限（含建立／刪除 trigger、DROP、TRUNCATE），網站不該拿它跑日常請求。
#   這支腳本讓網站改用 ri_runtime：
#     - ri_audit_log：只有 SELECT、INSERT（Audit 只能新增，至少保存二十年）
#     - ri_entity_snapshots：SELECT、INSERT，另加 UPDATE（2026-11-13 業主決定：未 Announce 的草稿只留一份最新副本）；
#       trigger 只放行「案件仍是 Draft 的 draft_updated 副本」，其餘 UPDATE 與所有 DELETE 照舊拒絕
#     - django_migrations、django_content_type、auth_permission：只讀
#     - django_session、ri_case_documents：可 DELETE
#     - ri_production_exclusions、ri_data_migration_items：只有 SELECT、INSERT（排除紀錄、轉換對照只新增，不修改也不刪除）
#     - 其餘所有資料表：SELECT、INSERT、UPDATE，沒有 DELETE
#       （對應「案件與已被引用的主檔永不實體刪除，只能停用／封存」）
#     - 沒有 DDL、沒有 TRIGGER、沒有 DROP／TRUNCATE
#   trigger 由 root 建立，ri_runtime 無法移除。
#
# 何時執行：每次 migrate 之後（新資料表才會拿到權限）。可重複執行。用 scripts/migrate.sh 一次完成兩件事。
set -euo pipefail
cd "$(dirname "$0")/.."

# 預設對正式環境；獨立測試環境（scripts/run_isolated_qa.sh）會指定自己的容器與密碼檔
MYSQL_CONTAINER="${MYSQL_CONTAINER:-ri-mysql}"
RUNTIME_PW="$(cat "${RUNTIME_PW_FILE:-secrets/mysql_runtime_password}")"
DB=ri_system
mysql_root() {  # 密碼在容器內讀取，不出現在命令列或日誌；有任何 ERROR 就中止
  local out
  out=$(docker exec -i "$MYSQL_CONTAINER" sh -c 'mysql -uroot -p"$(cat /run/secrets/mysql_root_password)" '"$1"' 2>&1' | grep -v 'Using a password' || true)
  if grep -q '^ERROR' <<<"$out"; then echo "$out" >&2; exit 1; fi
  if [ -n "$out" ]; then printf '%s\n' "$out"; fi
}

TABLES=$(echo "SELECT table_name FROM information_schema.tables WHERE table_schema='${DB}' AND table_type='BASE TABLE' ORDER BY 1" | mysql_root "-N ${DB}")
[ -n "$TABLES" ] || { echo "could not list tables" >&2; exit 1; }

APPEND_ONLY="ri_audit_log ri_entity_snapshots ri_legacy_audit"
# ri_legacy_import_batches：2026-11-11 起網頁匯入（系統管理員），一般權限 SELECT／INSERT／UPDATE，仍無 DELETE。
READ_ONLY="django_migrations django_content_type auth_permission"
CAN_DELETE="django_session ri_case_documents"
INSERT_ONLY="ri_production_exclusions ri_data_migration_items"
in_list() { [[ " $2 " == *" $1 "* ]]; }

{
  echo "DROP USER IF EXISTS 'ri_runtime'@'%';"
  echo "CREATE USER 'ri_runtime'@'%' IDENTIFIED BY '${RUNTIME_PW}';"
  for t in $TABLES; do
    if   [ "$t" = "ri_entity_snapshots" ]; then privs="SELECT, INSERT, UPDATE"   # UPDATE 由下方 trigger 限制在草稿副本
    elif in_list "$t" "$APPEND_ONLY"; then privs="SELECT, INSERT"
    elif in_list "$t" "$INSERT_ONLY"; then privs="SELECT, INSERT"
    elif in_list "$t" "$READ_ONLY";   then privs="SELECT"
    elif in_list "$t" "$CAN_DELETE";  then privs="SELECT, INSERT, UPDATE, DELETE"
    else                                   privs="SELECT, INSERT, UPDATE"
    fi
    echo "GRANT ${privs} ON \`${DB}\`.\`${t}\` TO 'ri_runtime'@'%';"
  done

  # Audit / Snapshot 不可變（連 root 的 UPDATE / DELETE 都會被拒絕，要改必須先明確移除 trigger）
  for t in $APPEND_ONLY; do
    echo "DROP TRIGGER IF EXISTS \`${t}_no_update\`;"
    echo "CREATE TRIGGER \`${t}_no_update\` BEFORE UPDATE ON \`${t}\` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '${t} is append-only: UPDATE is not allowed';"
    echo "DROP TRIGGER IF EXISTS \`${t}_no_delete\`;"
    echo "CREATE TRIGGER \`${t}_no_delete\` BEFORE DELETE ON \`${t}\` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '${t} is append-only: DELETE is not allowed';"
  done
  # 2026-11-13 業主決定：未 Announce 的草稿只保留一份最新副本。把 ri_entity_snapshots 的「禁止 UPDATE」改成有條件放行：
  # 只有 entity_type='case'、reason='draft_updated'、識別欄位不變，且該案件目前仍是 Draft 的那一筆可以被覆蓋。
  # 案件 Announce 後（status 不再是 draft）其所有副本恢復不可修改；DELETE trigger 不變。
  echo "DROP TRIGGER IF EXISTS \`ri_entity_snapshots_no_update\`;"
  echo "DELIMITER \$\$"
  echo "CREATE TRIGGER \`ri_entity_snapshots_no_update\` BEFORE UPDATE ON \`ri_entity_snapshots\` FOR EACH ROW BEGIN IF NOT (OLD.entity_type = 'case' AND OLD.snapshot_reason = 'draft_updated' AND NEW.id = OLD.id AND NEW.entity_type = OLD.entity_type AND NEW.entity_id = OLD.entity_id AND NEW.snapshot_reason = OLD.snapshot_reason AND EXISTS (SELECT 1 FROM \`ri_cases\` WHERE case_uid = REPLACE(OLD.entity_id, '-', '') AND status = 'draft')) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ri_entity_snapshots is append-only: only the draft snapshot of a case that is still a Draft may be replaced'; END IF; END\$\$"
  echo "DELIMITER ;"
  # Audit 保存期至少 20 年（對應 Alpha 的 ri_audit_log_retention_minimum）
  echo "DROP TRIGGER IF EXISTS \`ri_audit_log_retention_min\`;"
  echo "DELIMITER \$\$"
  echo "CREATE TRIGGER \`ri_audit_log_retention_min\` BEFORE INSERT ON \`ri_audit_log\` FOR EACH ROW BEGIN IF NEW.retention_until < DATE_ADD(NEW.occurred_at, INTERVAL 20 YEAR) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ri_audit_log retention must be at least 20 years'; END IF; END\$\$"
  echo "DELIMITER ;"
} > /tmp/ri_db_harden.$$.sql

# 含密碼的暫存檔只有自己可讀，用完立刻刪除
chmod 600 /tmp/ri_db_harden.$$.sql
trap 'rm -f /tmp/ri_db_harden.$$.sql' EXIT
mysql_root "${DB}" < /tmp/ri_db_harden.$$.sql

echo "ri_runtime privileges applied to $(echo "$TABLES" | wc -w) tables; audit triggers installed."
