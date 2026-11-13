#!/usr/bin/env bash
# 每天清理已過期的登入紀錄（django_session），避免無限累積（2026-11-13 業主決定）。
# 只刪「已過期」的紀錄，不影響登入中的使用者。安裝到目前使用者的 crontab，可重複執行。
#   scripts/install_session_cleanup_cron.sh            安裝或更新（每天 05:40，台灣時間）
#   scripts/install_session_cleanup_cron.sh --remove   移除
# 輸出附加到 logs/session-cleanup.log（不進版控）。
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
BEGIN="# >>> ri-system session cleanup (managed by install_session_cleanup_cron.sh)"
END="# <<< ri-system session cleanup"

current="$(crontab -l 2>/dev/null || true)"
kept="$(printf '%s\n' "$current" | awk -v b="$BEGIN" -v e="$END" '$0 == b {skip = 1} !skip && NF {print} $0 == e {skip = 0}')"

if [ "${1:-}" = "--remove" ]; then
  printf '%s\n' "$kept" | crontab -
  echo "session cleanup cron entry removed"
  exit 0
fi

mkdir -p "$ROOT/logs"
block="$BEGIN
40 5 * * * cd $ROOT && echo \"\$(date -Is) clearsessions \$(docker exec ri-backend python manage.py clearsessions 2>&1 | tail -1)\" >> logs/session-cleanup.log
$END"

{ [ -n "$kept" ] && printf '%s\n' "$kept"; printf '%s\n' "$block"; } | crontab -
echo "session cleanup cron entry installed:"
crontab -l | awk -v b="$BEGIN" -v e="$END" '$0 == b {show = 1} show {print} $0 == e {show = 0}'
