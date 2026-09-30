#!/usr/bin/env python3
"""Stage 4A1 engineering entry point; no formal execution mode."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["MPLBACKEND"] = "Agg"
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalar_baseline.stage4_search import (  # noqa: E402
    CAMPAIGN_SEEDS, DEVELOPMENT_SEEDS, FORMAL_ROOT, HELDOUT_SEEDS,
    METHODS, OPPORTUNITIES, protected_snapshot, source_identity,
)
from scalar_baseline.stage4_space import BASELINE  # noqa: E402


def dry_run() -> dict:
    return {
        "mode": "dry-run", "objective_status": "OBJECTIVE_VIABLE_WITH_PREREGISTERED_AMENDMENT",
        "methods": METHODS, "campaign_seeds": CAMPAIGN_SEEDS,
        "development_seeds": DEVELOPMENT_SEEDS, "heldout_seeds": HELDOUT_SEEDS,
        "opportunities_per_campaign": OPPORTUNITIES,
        "total_candidate_opportunities": len(METHODS) * len(CAMPAIGN_SEEDS) * OPPORTUNITIES,
        "baseline_candidate_sha256": BASELINE.digest(),
        "source_identity": source_identity(ROOT, require_clean=False),
        "protected_snapshot_sha256": protected_snapshot(ROOT)["sha256"],
        "formal_results_root_exists": (ROOT / FORMAL_ROOT).exists(),
        "formal_candidate_evaluations": 0,
        "formal_campaigns": 0,
        "external_llm_calls": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dry-run",))
    parser.parse_args(argv)
    print(json.dumps(dry_run(), indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
