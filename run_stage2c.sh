#!/usr/bin/env bash
set -euo pipefail

STAGE2C_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export MPLBACKEND=Agg
export MPLCONFIGDIR="${TMPDIR:-/tmp}/ant-colony-stage2c-matplotlib"
export XDG_CACHE_HOME="${TMPDIR:-/tmp}/ant-colony-stage2c-cache"

python3 -B "$STAGE2C_PROJECT_DIR/scripts/run_stage2c.py" "$@"
