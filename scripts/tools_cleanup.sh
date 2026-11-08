#!/usr/bin/env bash
# 開發工具舊版本與暫存清理（保留規則見 VM-RULES.md §3「Docker 映像保留」下一條）
#   scripts/tools_cleanup.sh          預覽（不刪任何東西）
#   scripts/tools_cleanup.sh --apply  實際刪除
# 只處理執行者自己的家目錄與 /tmp/ri-*（不碰其他帳號）。每個工具一律保留：
#   執行中的版本、「目前版本」連結指向的版本、最新的版本；其餘超過 KEEP_DAYS 天才刪。
# 工具正在安裝／更新（有 install.lock 或 .lock 檔且在 1 小時內）時跳過該工具。
set -euo pipefail
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
KEEP_DAYS="${KEEP_DAYS:-7}"
echo "=== $(date -Is) tools_cleanup $([[ $APPLY == 1 ]] && echo APPLY || echo DRY-RUN) keep_days=$KEEP_DAYS user=$(id -un)"
df -h / | tail -1

python3 -I - "$APPLY" "$KEEP_DAYS" <<'EOF'
import json, os, shutil, sys, time
from pathlib import Path

APPLY, DAYS = sys.argv[1] == '1', int(sys.argv[2])
H = Path.home()
NOW = time.time()
OLD = NOW - DAYS * 86400
total = [0, 0]  # bytes, count

# 執行中的程式（只看自己帳號的程序：執行檔與命令列）
running = set()
for p in Path('/proc').iterdir():
    if not p.name.isdigit():
        continue
    try:
        running.add(os.readlink(p / 'exe'))
    except OSError:
        pass
    try:
        running.update(a for a in (p / 'cmdline').read_bytes().decode(errors='ignore').split('\0') if a.startswith('/'))
    except OSError:
        pass


def in_use(path):
    s = str(path)
    return any(r == s or r.startswith(s + '/') for r in running)


def size(path):
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    return sum(f.lstat().st_size for f in path.rglob('*') if not f.is_symlink() and f.is_file())


def target(link):
    try:
        return Path(os.path.realpath(link))
    except OSError:
        return None


def locked(*locks):
    return any(l.exists() and NOW - l.stat().st_mtime < 3600 for l in locks)


def remove(path, why):
    b = size(path)
    total[0] += b; total[1] += 1
    print(f'  刪除 {path}  ({b / 1e6:.0f} MB) {why}')
    if APPLY:
        shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()


def versions(name, folder, current_links=(), locks=()):
    """folder 底下每個項目是一個版本；保留執行中／目前連結／最新／KEEP_DAYS 天內。"""
    folder = Path(folder)
    if not folder.is_dir():
        return
    print(f'[{name}] {folder}')
    if locked(*locks):
        print('  正在安裝或更新，略過')
        return
    items = [p for p in folder.iterdir() if not p.name.startswith('.') and not p.name.endswith(('.json', '.lock'))]
    if not items:
        return
    newest = max(items, key=lambda p: p.lstat().st_mtime)
    cur = {target(l) for l in current_links if Path(l).exists()}
    for p in sorted(items):
        keep = []
        if in_use(p): keep.append('執行中')
        if any(c and (c == p.resolve() or str(c).startswith(str(p.resolve()) + '/')) for c in cur): keep.append('目前版本')
        if p == newest: keep.append('最新')
        if p.lstat().st_mtime > OLD: keep.append(f'{DAYS}天內')
        if keep:
            print(f'  保留 {p.name}（{"、".join(keep)}）')
        else:
            remove(p, '')


# 1. Codex
versions('Codex CLI', H / '.codex/packages/standalone/releases',
         [H / '.codex/packages/standalone/current', H / '.local/bin/codex'],
         [H / '.codex/packages/standalone/install.lock'])
versions('Codex 背景服務', H / '.codex/packages/app-server-daemon/releases',
         [H / '.codex/packages/app-server-daemon/current'],
         [H / '.codex/packages/app-server-daemon/install.lock'])
# 2. Claude Code
versions('Claude Code', H / '.local/share/claude/versions', [H / '.local/bin/claude'])
versions('Claude Code 遠端執行檔', H / '.claude/remote/ccd-cli')
# 3. VS Code 伺服器
versions('VS Code 伺服器', H / '.vscode-server/cli/servers', [], [])

# 4. VS Code 擴充套件：只刪 extensions.json 沒登記、沒在執行、超過 KEEP_DAYS 天的
ext = H / '.vscode-server/extensions'
if (ext / 'extensions.json').is_file():
    print(f'[VS Code 擴充套件] {ext}')
    try:
        reg = {x.get('relativeLocation') for x in json.loads((ext / 'extensions.json').read_text())}
    except Exception as e:
        reg = None
        print(f'  extensions.json 無法讀取（{e}），略過')
    if reg:
        for p in sorted(ext.iterdir()):
            if not p.is_dir() or p.name.startswith('.'):
                continue
            if p.name in reg or in_use(p) or p.stat().st_mtime > OLD:
                continue
            remove(p, '（未登記的舊版）')
cache = H / '.vscode-server/data/CachedExtensionVSIXs'
if cache.is_dir():
    print(f'[VS Code 擴充安裝檔快取] {cache}')
    for p in sorted(cache.iterdir()):
        if not p.name.startswith('.') and p.lstat().st_mtime < OLD:
            remove(p, '')

# 5. /tmp 裡自己的 ri-* 暫存資料夾
print('[/tmp 暫存] /tmp/ri-*')
uid = os.getuid()
for p in sorted(Path('/tmp').glob('ri-*')):
    try:
        st = p.lstat()
    except OSError:
        continue
    if st.st_uid == uid and st.st_mtime < OLD and not in_use(p):
        try:
            remove(p, '')
        except PermissionError as e:
            print(f'  無法刪除 {p}：{e}')

print(f'--- {"已刪除" if APPLY else "預計刪除"} {total[1]} 項，約 {total[0] / 1e9:.2f} GB' + ('' if APPLY else '（預覽模式，未刪除）'))
EOF
df -h / | tail -1
