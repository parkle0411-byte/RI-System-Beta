#!/usr/bin/env bash
# 建環境 → 造資料 → 依序量各組設定（背景執行；全部結束後環境保留，要手動 down.sh）
cd "$(dirname "$0")/../.."
export STRESS_OUT="${STRESS_OUT:-/tmp/ri-stress-out}"; mkdir -p "$STRESS_OUT/matrix"
qa/stress/up.sh || exit 1
docker exec -i ri-stress-backend python manage.py shell < qa/stress/seed.py 2>&1 | grep -v -i "imported auto" | tail -4
qa/stress/matrix.sh A_2w_bp512   2 1 512
qa/stress/matrix.sh C_4w_bp512   4 1 512 mixed
qa/stress/matrix.sh D_2w4t_bp512 2 4 512 mixed
qa/stress/matrix.sh B_3w_bp512   3 1 512 mixed
echo ALL-DONE
