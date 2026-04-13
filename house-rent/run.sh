#!/bin/bash
# 台南租屋日報
#
# 用法：
#   ./run.sh now      # 立即執行
#   ./run.sh routine  # 排程用，輸出寫入 log
#
# crontab:
#   15 12 * * * /home/jason_yp_wang/yp-routine/house-rent/run.sh routine

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export DISCORD_WEBHOOK_HOUSE="https://discord.com/api/webhooks/1493193679890939974/SGWZGMP0BK3gOXP-prKnzkALRRGM0l954t-69beUeXLedLOzAeWeb0W0pcDDYo6muwAX"

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
