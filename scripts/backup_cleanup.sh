#!/usr/bin/env bash
# 舊備份與舊畫面測試截圖清理（2026-11-24 業主決定，規則見 VM-RULES.md §3「備份保留」）
#   scripts/backup_cleanup.sh          預覽（不刪任何東西）
#   scripts/backup_cleanup.sh --apply  實際刪除
# 刪除：backups/ 第一層超過 BACKUP_DAYS（14）天的項目（含打包檔），qa/ui/out.previous-* 超過 SHOT_DAYS（7）天的資料夾。
# 天數取「名稱裡的日期」與「檔案修改時間」較新的一個，寧可晚刪、不提早刪；只處理這兩處的第一層，不跟隨連結。
set -euo pipefail
cd "$(dirname "$0")/.."
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
BACKUP_DAYS="${BACKUP_DAYS:-14}"; SHOT_DAYS="${SHOT_DAYS:-7}"
echo "=== $(date -Is) backup_cleanup $([[ $APPLY == 1 ]] && echo APPLY || echo DRY-RUN) backup_days=$BACKUP_DAYS shot_days=$SHOT_DAYS"
df -h / | tail -1

python3 -I - "$APPLY" "$BACKUP_DAYS" "$SHOT_DAYS" <<'EOF'
import re, shutil, sys, time
from datetime import datetime
from pathlib import Path

APPLY, BACKUP_DAYS, SHOT_DAYS = sys.argv[1] == '1', int(sys.argv[2]), int(sys.argv[3])
NOW = time.time()
STAMP = re.compile(r'(20\d{6})(?:[_-](\d{6}))?')


def made_at(path):
    """名稱裡的日期（取最晚的一個）與修改時間，取較新者。"""
    times = [path.lstat().st_mtime]
    for day, clock in STAMP.findall(path.name):
        try:
            times.append(datetime.strptime(day + (clock or '235959'), '%Y%m%d%H%M%S').timestamp())
        except ValueError:
            pass
    return max(times)


def size(path):
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    return sum(f.lstat().st_size for f in path.rglob('*') if not f.is_symlink() and f.is_file())


def sweep(title, items, days):
    old = NOW - days * 86400
    gone, kept, freed = 0, 0, 0
    print(f'## {title}（超過 {days} 天刪除）')
    for path in sorted(items, key=made_at):
        when = made_at(path)
        if when >= old:
            kept += 1
            continue
        b = size(path)
        gone += 1; freed += b
        print(f'  刪除 {path}  ({b / 1e6:.1f} MB，{(NOW - when) / 86400:.0f} 天)')
        if APPLY:
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
    print(f'  合計：{"已刪除" if APPLY else "將刪除"} {gone} 項、{freed / 1e6:.0f} MB；保留 {kept} 項')


sweep('backups/', [p for p in Path('backups').iterdir()], BACKUP_DAYS)
sweep('qa/ui/out.previous-*', [p for p in Path('qa/ui').glob('out.previous-*') if p.is_dir() and not p.is_symlink()], SHOT_DAYS)
EOF
df -h / | tail -1
