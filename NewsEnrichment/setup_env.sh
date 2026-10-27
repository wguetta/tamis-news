#!/bin/bash
set -euo pipefail

VENV="/home/ec2-user/NewsEnrichmentEnv"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3.11 >/dev/null 2>&1; then
  echo "python3.11 is required to create ${VENV}" >&2
  exit 1
fi

python3.11 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$SCRIPT_DIR/requirements.txt"

echo "Virtualenv ready: $VENV"
