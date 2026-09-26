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
for f in accounting payment-terms case-draft signed-slip-reminders production-report; do
  want=$(grep -o "lib/$f.js\` | [0-9]* | \`[0-9a-f]*" backend/qa/alpha_js/MANIFEST.md | grep -o '[0-9a-f]\{64\}')
  got=$(sha256sum "backend/qa/alpha_js/lib/$f.js" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "  Alpha 原始碼副本 lib/$f.js 的雜湊與 MANIFEST.md 不符，請勿手動修改" >&2; exit 1; }
done

# 節錄檔同樣要與 MANIFEST.md 記錄的雜湊相同
for f in api-excerpts case-documents-excerpts accounting-excerpts production-excerpts dashboard-excerpts render-pdf-excerpts; do
  want=$(grep -o "excerpts/$f.js\` | \`[0-9a-f]*" backend/qa/alpha_js/MANIFEST.md | grep -o '[0-9a-f]\{64\}')
  got=$(sha256sum "backend/qa/alpha_js/excerpts/$f.js" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "  節錄檔 excerpts/$f.js 的雜湊與 MANIFEST.md 不符，請勿手動修改" >&2; exit 1; }
done

# 前端的 Alpha 原樣副本（Production Report 的 Excel 產生程式）同樣不可改動
[ "$(sha256sum frontend/src/alpha/production-xlsx.js | cut -d' ' -f1)" = "256db219f84aa2e56c9e1a36c81541c1fe7a560b0a0f9054e2253773808dcf59" ] \
  || { echo "  frontend/src/alpha/production-xlsx.js 與 Alpha 的 public/production-xlsx.js 不同，請勿手動修改" >&2; exit 1; }
# 產生 Word／PDF 的 Alpha 原樣副本（public/ 下同名檔案，v53）
while read -r f want; do
  [ "$(sha256sum "frontend/public/alpha-documents/$f" | cut -d' ' -f1)" = "$want" ] \
    || { echo "  frontend/public/alpha-documents/$f 與 Alpha 的 public/$f 不同，請勿手動修改" >&2; exit 1; }
done <<'HASHES'
docx-generator.js 6726dda0f766ac4a6b4dbc084aa857a182f93cb5639c05d02b7afc9d23ebbbad
docx-templates.js b06c99814f1b0b3ecd556bdd3fe921f135363ed50a506f9f5b91d0fb2e3a0ef7
pdf-assets.js 45736bdb789036bdfdbe36d3e764992af79fd6b92ec1c8af2df040db0d5711fa
pdf-generator.js f403fe41074f259066e8d192afa2adaa16828b59610dc9893b9841cdfbbb7d21
HASHES

docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/backend/qa/alpha_js:/alpha:ro" -v "$PWD/backend/qa/calc:/calc:ro" -v "$WORK:/data" node:22-alpine sh -c '
    mkdir -p /tmp/w/node_modules && cp -r /alpha/lib /tmp/w/lib && cp /alpha/excerpts/*.js /tmp/w/lib/ && cp /calc/harness.mjs /tmp/w/ &&
    ln -s ../lib /tmp/w/node_modules/lib && echo "{\"type\":\"module\"}" > /tmp/w/package.json &&
    cd /tmp/w && node harness.mjs /data/vectors.json > /data/js.json'

python3 - "$WORK" <<'PY' | docker exec -i ri-backend python -m qa.calc.compare
import json, sys
w = sys.argv[1]
json.dump({"vectors": json.load(open(f"{w}/vectors.json")), "js": json.load(open(f"{w}/js.json"))}, sys.stdout)
PY
