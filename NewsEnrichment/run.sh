#!/bin/bash
source /home/ec2-user/NewsEnrichmentEnv/bin/activate

ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.env"
set -a
source "$ENV_FILE"
set +a

RUN_ID=$(date -u +%Y%m%d)
LOG="/home/ec2-user/NewsEnrichment/logs/run-${RUN_ID}.log"

while true; do
  echo "=== Attempt at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG"
  LOAD_HOURS=24 MAX_WORKERS=12 BATCH_SIZE=50 python /home/ec2-user/NewsEnrichment/main.py --run-id "$RUN_ID" >> "$LOG" 2>&1
  if [ $? -eq 0 ]; then
    echo "=== Success ===" >> "$LOG"
    break
  fi
  echo "=== Crashed, retrying in 5 sec ===" >> "$LOG"
  sleep 5
done

echo "=== Shutting down at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG"
shutdown -h now
