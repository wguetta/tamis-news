#!/bin/bash
cd /home/ec2-user/NewsClustering
source .venv/bin/activate

ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.env"
set -a
source "$ENV_FILE"
set +a

python /home/ec2-user/NewsClustering/main.py


echo "=== Shutting down at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
shutdown -h now
