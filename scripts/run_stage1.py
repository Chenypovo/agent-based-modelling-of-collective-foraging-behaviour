#!/usr/bin/env python3
"""Repository-local launcher that does not require package installation."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

PROCESS_START = time.perf_counter()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
cache_root = Path(tempfile.gettempdir()) / "ant-walks-cache"
cache_root.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(cache_root))

from ant_walks.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(process_start=PROCESS_START))
