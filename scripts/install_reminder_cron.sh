#!/usr/bin/env bash
# 安裝每天的提醒排程到目前使用者的 crontab（需要在 docker 群組）。可重複執行：只會替換本腳本管理的那一段。
#   Signed Slip 提醒  每天台北 09:00（Alpha：0 1 * * * UTC）
#   付款提醒          每天台北 09:30（Alpha：30 1 * * * UTC）
# 主機時區必須是 Asia/Taipei（腳本會檢查）。輸出（JSON 結果）附加到 logs/reminders.log（不進版控）。
#
#   scripts/install_reminder_cron.sh            安裝或更新
#   scripts/install_reminder_cron.sh --remove   移除
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
BEGIN="# >>> ri-system reminders (managed by install_reminder_cron.sh)"
END="# <<< ri-system reminders"

current="$(crontab -l 2>/dev/null || true)"
kept="$(printf '%s\n' "$current" | awk -v b="$BEGIN" -v e="$END" '$0 == b {skip = 1} !skip && NF {print} $0 == e {skip = 0}')"

if [ "${1:-}" = "--remove" ]; then
  printf '%s\n' "$kept" | crontab -
  echo "reminder cron entries removed"
  exit 0
fi

tz="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo unknown)"
[ "$tz" = "Asia/Taipei" ] || { echo "host time zone is $tz, expected Asia/Taipei" >&2; exit 1; }
mkdir -p "$ROOT/logs"

block="$BEGIN
0 9 * * * cd $ROOT && echo \"\$(date -Is) signed-slip \$(docker exec ri-backend python manage.py run_signed_slip_reminders 2>&1)\" >> logs/reminders.log
30 9 * * * cd $ROOT && echo \"\$(date -Is) payment \$(docker exec ri-backend python manage.py run_payment_reminders 2>&1)\" >> logs/reminders.log
$END"

{ [ -n "$kept" ] && printf '%s\n' "$kept"; printf '%s\n' "$block"; } | crontab -
echo "reminder cron entries installed:"
crontab -l | awk -v b="$BEGIN" -v e="$END" '$0 == b {show = 1} show {print} $0 == e {show = 0}'
