#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MPLCONFIGDIR="${TMPDIR:-/tmp}/ant-colony-stage2b-matplotlib"
export XDG_CACHE_HOME="${TMPDIR:-/tmp}/ant-colony-stage2b-cache"

python3 "$PROJECT_DIR/scripts/run_stage2b.py" "$@"
