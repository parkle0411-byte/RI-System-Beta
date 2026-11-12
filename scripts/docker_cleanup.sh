#!/usr/bin/env bash
# Docker 空間清理（保留規則見 VM-RULES.md §3「Docker 映像保留」）
#   scripts/docker_cleanup.sh          預覽（不刪任何東西）
#   scripts/docker_cleanup.sh --apply  實際刪除
# 只處理 ri-* 自建映像；第三方映像（mysql、nginx、node、python…）不動。
# 一律保留：容器使用中（含已停止）、7 天內建立或 tag 日期在 7 天內、
#           VM-RULES／腳本／compose 有寫到（before-* 回滾點除外）。
# before-* 回滾點（2026-11-12 業主決定）：7 天內全部保留，另外每個映像庫不論多舊至少保留最新
#           ROLLBACK_KEEP_MIN 個（預設 10）；超過的刪除，即使 VM-RULES 的部署紀錄有寫到。
# 另清：超過 7 天的建置快取、沒有名字（dangling）的映像。
set -euo pipefail
cd "$(dirname "$0")/.."
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
KEEP_DAYS="${KEEP_DAYS:-7}"
ROLLBACK_KEEP_MIN="${ROLLBACK_KEEP_MIN:-10}"
[[ -f VM-RULES.md ]] || { echo "找不到 VM-RULES.md，中止"; exit 1; }

echo "=== $(date -Is) docker_cleanup $([[ $APPLY == 1 ]] && echo APPLY || echo DRY-RUN) keep_days=$KEEP_DAYS"
df -h / | tail -1

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
docker images --format '{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}\t{{.Size}}' > "$TMP/images.tsv"
docker ps -aq | xargs -r docker inspect -f '{{.Image}}' | sed 's/^sha256://' | cut -c1-12 > "$TMP/in_use.txt"
grep -rhoE '[a-z0-9._/-]+(:[A-Za-z0-9._-]+|@sha256:[0-9a-f]{12})' \
  --include='*.md' --include='*.sh' --include='*.y*ml' --include='*.py' --include='Dockerfile*' \
  --exclude-dir=backups --exclude-dir=node_modules --exclude-dir=.git . 2>/dev/null | sort -u > "$TMP/refs.txt" || true

python3 -I - "$TMP" "$KEEP_DAYS" "$ROLLBACK_KEEP_MIN" > "$TMP/delete.txt" <<'EOF'
import sys, re, datetime, collections
tmp, days, rollback_min = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
cutoff = datetime.date.today() - datetime.timedelta(days=days)
rows = [l.rstrip('\n').split('\t') for l in open(f'{tmp}/images.tsv') if l.strip()]
in_use = {l.strip() for l in open(f'{tmp}/in_use.txt') if l.strip()}
refs = {l.strip() for l in open(f'{tmp}/refs.txt')}
ref_digests = {r.split('@sha256:')[1][:12] for r in refs if '@sha256:' in r}
ref_tags = {r.split(':', 1)[1] for r in refs if ':' in r and '@' not in r}
pat = re.compile(r'^before-(.+)-(\d{8}(?:_\d{6})?)$')
# 回滾點：每個映像庫依 tag 時間排序，最新的 rollback_min 個一定保留。
stamps = collections.defaultdict(list)
for repo, tag, iid, created, size in rows:
    m = pat.match(tag)
    if m: stamps[repo].append((m[2].ljust(15, '0'), tag))
newest = {(repo, tag) for repo, items in stamps.items() for _, tag in sorted(items, reverse=True)[:rollback_min]}
def recent(repo, tag, created):
    if datetime.date.fromisoformat(created[:10]) >= cutoff: return True
    return any(datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])) >= cutoff
               for d in re.findall(r'(20\d{2}[01]\d[0-3]\d)', tag) if 1 <= int(d[4:6]) <= 12 and 1 <= int(d[6:]) <= 31)
reasons = {}
for repo, tag, iid, created, size in rows:
    if repo == '<none>' or tag == '<none>': continue
    full = f'{repo}:{tag}'; why = []
    if not repo.startswith('ri-'): why.append('third-party')
    if iid in in_use or iid in ref_digests: why.append('in-use')
    m = pat.match(tag)
    if m:
        # 回滾點只看 tag 上的部署日期（映像本身的建立日期是「部署前那一版」的日期，不代表回滾點的新舊）。
        if recent(repo, tag, '1970-01-01'): why.append('recent')
        if (repo, tag) in newest: why.append('newest-rollbacks')
    else:
        if recent(repo, tag, created): why.append('recent')
        if full in refs or tag in ref_tags: why.append('referenced')
    reasons[full] = (why, iid, size)
by_id = collections.defaultdict(list)
for f, (w, i, s) in reasons.items(): by_id[i].append(f)
for f, (w, i, s) in sorted(reasons.items()):
    if not w:
        whole = all(not reasons[g][0] for g in by_id[i])
        print(f"{f}\t{i}\t{s}\t{'image' if whole else 'alias'}")
EOF

n=$(wc -l < "$TMP/delete.txt")
echo "--- 要移除的 tag：$n 個（image=映像會整個刪除，alias=只移除多餘名稱）"
cat "$TMP/delete.txt"

if [[ $APPLY == 1 ]]; then
  fail=0
  while IFS=$'\t' read -r t _; do
    docker rmi "$t" >/dev/null 2>&1 || { echo "FAIL rmi $t"; fail=$((fail+1)); }
  done < "$TMP/delete.txt"
  echo "--- rmi 完成，失敗 $fail 個"
  docker image prune -f | tail -1
  docker builder prune -f --filter "until=$((KEEP_DAYS*24))h" | tail -1
else
  echo "--- 預覽模式：未刪除。另會清超過 ${KEEP_DAYS} 天的建置快取與 dangling 映像。"
fi
df -h / | tail -1
