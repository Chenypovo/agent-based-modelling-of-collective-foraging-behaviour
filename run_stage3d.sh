#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
export MPLBACKEND=Agg
python3 -B scripts/run_stage3d.py "$@"
