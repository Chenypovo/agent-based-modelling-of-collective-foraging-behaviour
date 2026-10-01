#!/usr/bin/env python3
"""Post-hoc description of food-B uptake after relocation, from stored H1a runs (no simulation).

Per half-life: time from relocation (12,000) to the first food-B delivery, and the number of B
deliveries in [12,000, 18,000). Not used for the H1a verdict.
Writes results/h1a_baseline/posthoc_food_b.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "h1a_baseline"
RELOCATION, EARLY_END = 12000, 18000


def describe(rows: list[dict]) -> list[str]:
    lines = ["| Half-life | First B delivery after move, median [IQR] | No B delivery | "
             "B deliveries in [12,000, 18,000), median [IQR] |", "|---|---|---|---|"]
    for h in sorted({r["half_life"] for r in rows}):
        rs = [r for r in rows if r["half_life"] == h]
        first = [min((t for t in r["delivery_times_B"] if t >= RELOCATION), default=None) for r in rs]
        lag = [t - RELOCATION for t in first if t is not None]
        early = [sum(RELOCATION <= t < EARLY_END for t in r["delivery_times_B"]) for r in rs]
        q = lambda x: f"{np.median(x):,.0f} [{np.percentile(x, 25):,.0f}, {np.percentile(x, 75):,.0f}]"  # noqa: E731
        lines.append(f"| {h} | {q(lag) if lag else 'n/a'} | {first.count(None)} / {len(rs)} | {q(early)} |")
    return lines


def main() -> int:
    text = ["# Food-B uptake after relocation (post-hoc description; not used for the H1a verdict)", "",
            "Computed from stored `runs.json` by `scripts/h1a_posthoc_food_b.py`; no new simulation.", ""]
    for step, label in (("h1a", "Step 4, D = 0.01, seeds 2026240001-020"),
                        ("robust", "Step 5, D = 0.02, seeds 2026250001-020")):
        rows = json.loads((OUT / step / "runs.json").read_text())
        text += [f"## {label}", "", *describe(rows), ""]
    (OUT / "posthoc_food_b.md").write_text("\n".join(text))
    print("\n".join(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
