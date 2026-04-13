#!/bin/bash
# 台股財報追蹤（月營收 + 季報）
#
# 用法：
#   ./run.sh now      # 立即執行
#   ./run.sh routine  # 排程用，輸出寫入 log
#
# crontab（每天早上 9:05 檢查一次，季報/月營收公告時會觸發）:
#   5 9 * * * /home/jason_yp_wang/yp-routine/stock-earnings/run.sh routine

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export DISCORD_WEBHOOK_FINANCE="https://discord.com/api/webhooks/1493195106491043940/5r2byMJZ4nTLLL5bj6qsZYHz7wE53c_nuWUx401lRkF8GLXuRwgcStgxQ95GmRQ8OgR3"

MODE="${1:-now}"

run_job() {
  echo "=== $(TZ=Asia/Taipei date) ==="
  python3 "$SCRIPT_DIR/search.py"
  echo "=== 完成 ==="
}

case "$MODE" in
  now)     run_job ;;
  routine) mkdir -p "$SCRIPT_DIR/logs"; run_job >> "$SCRIPT_DIR/logs/cron.log" 2>&1 ;;
  *)       echo "用法: $0 {now|routine}"; exit 1 ;;
esac
