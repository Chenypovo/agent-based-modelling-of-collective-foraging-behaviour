#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cache_dir="${TMPDIR:-/tmp}/ant-colony-stage2-cache"
export MPLCONFIGDIR="$cache_dir/matplotlib"
export XDG_CACHE_HOME="$cache_dir"
mkdir -p "$MPLCONFIGDIR" "$XDG_CACHE_HOME/fontconfig"
cd "$project_dir"
exec python3 scripts/run_stage2.py "$@"
