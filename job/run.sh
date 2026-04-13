#!/bin/bash
# 104 AI 遠端職缺日報
#
# 用法：
#   ./run.sh now      # 立即執行，輸出到終端（開發用）
#   ./run.sh routine  # 排程執行，輸出到 log 檔（crontab 用）
#
# crontab 設定方式：
#   crontab -e
#   3 12 * * * /home/jason_yp_wang/yp-routine/job/run.sh routine

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export DISCORD_WEBHOOK="https://discord.com/api/webhooks/1491687759856013364/O8MnusOutTU3opVxCfVV_b9qHPeyzNZUJk8tOWRiiLnLzs79Y59X0_zHdC0KvumBL1rY"

MODE="${1:-now}"

run_job() {
  echo "=== $(TZ=Asia/Taipei date) ==="
  python3 "$SCRIPT_DIR/search_104.py"
  echo "=== 完成 ==="
}

case "$MODE" in
  now)
    run_job
    ;;
  routine)
    mkdir -p "$SCRIPT_DIR/logs"
    run_job >> "$SCRIPT_DIR/logs/cron.log" 2>&1
    ;;
  *)
    echo "用法: $0 {now|routine}"
    echo "  now     - 立即執行，輸出到終端"
    echo "  routine - 排程執行，輸出到 log 檔"
    exit 1
    ;;
esac
