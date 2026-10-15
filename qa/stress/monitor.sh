#!/usr/bin/env bash
# 取樣壓測容器的 CPU／記憶體（每 2 秒一次）寫到檔案；用法：monitor.sh start FILE ／ monitor.sh stop FILE ／ monitor.sh summary FILE
case "$1" in
  start) ( while true; do docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' ri-stress-backend ri-stress-mysql ri-stress-nginx 2>/dev/null | sed "s/^/$(date +%s),/" >> "$2"; sleep 1; done ) >/dev/null 2>&1 & echo $! > "$2.pid" ;;
  stop) kill "$(cat "$2.pid")" 2>/dev/null; rm -f "$2.pid" ;;
  summary) python3 - "$2" <<'PY'
import sys, collections
peak, avg, mem = collections.defaultdict(float), collections.defaultdict(list), collections.defaultdict(float)
for line in open(sys.argv[1]):
    p = line.strip().split(',')
    if len(p) < 4: continue
    name, cpu = p[1], float(p[2].rstrip('%') or 0)
    used = p[3].split('/')[0].strip()
    mb = float(used.rstrip('MiBGi')) * (1024 if 'GiB' in used else 1)
    peak[name] = max(peak[name], cpu); avg[name].append(cpu); mem[name] = max(mem[name], mb)
for n in sorted(peak):
    print(f"  {n:20s} CPU 平均 {sum(avg[n])/len(avg[n]):6.1f}%  尖峰 {peak[n]:6.1f}%（4 核心 = 最高 400%）  記憶體尖峰 {mem[n]:6.0f} MB")
PY
  ;;
esac
