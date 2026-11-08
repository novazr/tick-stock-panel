#!/usr/bin/env bash
# 一键：下载行情 → 12 版本回测对比 → 今日扫描 → 生成看板数据文件
# 用法：bash tools/swing-scanner/run.sh [输出目录]
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/out}
mkdir -p "$OUT/data" "$OUT/dash"

{ cat "$HERE/universe_ndx.txt"; [ -f "$HERE/watchlist.txt" ] && cat "$HERE/watchlist.txt"; echo QQQ; } \
  | tr -d '\r' | grep -v '^\s*$' | sort -u \
  | xargs -P 8 -I{} curl -sS -m 40 -A "Mozilla/5.0" \
      "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=10y&interval=1d&events=div,splits" \
      -o "$OUT/data/{}.json"

python3 -I -W ignore "$HERE/swing_compare.py" "$OUT/data"
python3 -I -W ignore "$HERE/swing_scan.py" "$OUT/data" "$OUT/dash/data.json"
python3 -I -W ignore "$HERE/build_datasets.py" "$OUT/data" "$OUT/dash/data.json" "$OUT/dash/ds"
echo "看板数据文件：$OUT/dash/ds"
