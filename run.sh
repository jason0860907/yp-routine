#!/bin/bash
# 104 AI 遠端職缺日報 - 每天中午 12 點由 crontab 觸發
# crontab 設定方式：
#   crontab -e
#   3 12 * * * /home/jason_yp_wang/yp-routine/run.sh >> /home/jason_yp_wang/yp-routine/logs/cron.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export DISCORD_WEBHOOK="https://discord.com/api/webhooks/1491687759856013364/O8MnusOutTU3opVxCfVV_b9qHPeyzNZUJk8tOWRiiLnLzs79Y59X0_zHdC0KvumBL1rY"

# 確保 log 目錄存在
mkdir -p "$SCRIPT_DIR/logs"

echo "=== $(TZ=Asia/Taipei date) ==="

# 讀取 prompt 並執行
claude -p "$(cat "$SCRIPT_DIR/prompt.md")" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
  2>&1

echo "=== 完成 ==="
