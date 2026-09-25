#!/usr/bin/env bash
# 套用 migration（用維護者 ri_app），然後重新套用 ri_runtime 的權限與 Audit trigger。
# 每次 migrate 都要做第二步，新資料表才會拿到權限。
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/manage_as_owner.sh migrate "$@"
./scripts/db_harden.sh
