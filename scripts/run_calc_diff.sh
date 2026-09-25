#!/usr/bin/env bash
# 案件計算的差異測試：Alpha 的 JavaScript（標準答案）對 VM 的 Python 移植版，同一批輸入、逐位比對。
#
#   1) 用固定亂數種子產生輸入向量（在 ri-backend 容器內，純 Python）
#   2) 在 Node 容器裡用 Alpha 的原始碼（backend/qa/alpha_js，逐位元組相同）跑一遍
#   3) 在 ri-backend 容器內用 Python 移植版跑一遍並比對；有任何不一致就以非 0 結束
#
# 可用環境變數 CALC_VECTORS 調整每類向量的數量（預設 1200，總共約 2 萬組）。
set -euo pipefail
cd "$(dirname "$0")/.."
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

docker exec ri-backend python -m qa.calc.vectors "${CALC_VECTORS:-1200}" > "$WORK/vectors.json"

# 驗證副本沒有被改動：雜湊必須與 MANIFEST.md 記錄的相同
for f in accounting payment-terms case-draft; do
  want=$(grep -o "lib/$f.js\` | [0-9]* | \`[0-9a-f]*" backend/qa/alpha_js/MANIFEST.md | grep -o '[0-9a-f]\{64\}')
  got=$(sha256sum "backend/qa/alpha_js/lib/$f.js" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "  Alpha 原始碼副本 lib/$f.js 的雜湊與 MANIFEST.md 不符，請勿手動修改" >&2; exit 1; }
done

docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/backend/qa/alpha_js:/alpha:ro" -v "$PWD/backend/qa/calc:/calc:ro" -v "$WORK:/data" node:22-alpine sh -c '
    mkdir -p /tmp/w/node_modules && cp -r /alpha/lib /tmp/w/lib && cp /calc/harness.mjs /tmp/w/ &&
    ln -s ../lib /tmp/w/node_modules/lib && echo "{\"type\":\"module\"}" > /tmp/w/package.json &&
    cd /tmp/w && node harness.mjs /data/vectors.json > /data/js.json'

python3 - "$WORK" <<'PY' | docker exec -i ri-backend python -m qa.calc.compare
import json, sys
w = sys.argv[1]
json.dump({"vectors": json.load(open(f"{w}/vectors.json")), "js": json.load(open(f"{w}/js.json"))}, sys.stdout)
PY
