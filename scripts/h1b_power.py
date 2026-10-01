#!/usr/bin/env python3
"""H1b Step 1: number of seeds from stored H1a runs (no simulation). See docs/H1B_ANALYSIS_PLAN.md.

Pool = paired tau for half-life (1000, 500) and (1000, 2000), same seed. Per n: draw n pairs with
replacement, randomly swap members, shrink recovered "hetero" tau by 20%, paired bootstrap CI of the
difference in medians; detection = delta < 0 and CI excludes 0.
Writes results/h1b_heterogeneity/power/power.json + power.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "h1b_heterogeneity" / "power"
CENSOR, EFFECT, REPS, BOOT, SEED = 24000, 0.8, 1000, 1000, 20261001
NS = tuple(range(20, 101, 10))


def pool(step: str) -> np.ndarray:
    rows = json.loads((ROOT / "results" / "h1a_baseline" / step / "runs.json").read_text())
    tau = {(r["half_life"], r["seed"]): float(r["tau"]) for r in rows}
    seeds = sorted({r["seed"] for r in rows})
    return np.array([(tau[(1000, s)], tau[(h, s)]) for h in (500, 2000) for s in seeds])


def detection_rate(pairs: np.ndarray, n: int, effect: float, rng: np.random.Generator) -> float:
    hits = 0
    for _ in range(REPS):
        draw = pairs[rng.integers(0, len(pairs), n)]
        swap = rng.random(n) < 0.5
        homo = np.where(swap, draw[:, 1], draw[:, 0])
        het = np.where(swap, draw[:, 0], draw[:, 1])
        het = np.where(het < CENSOR, het * effect, het)
        idx = rng.integers(0, n, size=(BOOT, n))
        boot = np.median(het[idx], axis=1) - np.median(homo[idx], axis=1)
        delta = np.median(het) - np.median(homo)
        hits += delta < 0 and np.percentile(boot, 97.5) < 0
    return hits / REPS


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    result = {}
    for step in ("h1a", "robust"):
        pairs = pool(step)
        diff = pairs[:, 1] - pairs[:, 0]
        result[step] = {
            "n_pairs": len(pairs), "censored_share": float(np.mean(pairs == CENSOR)),
            "paired_diff_median": float(np.median(diff)),
            "paired_diff_iqr": [float(np.percentile(diff, 25)), float(np.percentile(diff, 75))],
            "tau_median": float(np.median(pairs)),
            "power_20pct": {n: detection_rate(pairs, n, EFFECT, rng) for n in NS},
            "false_detection": {n: detection_rate(pairs, n, 1.0, rng) for n in (20, 60, 100)}}
        print(step, result[step], flush=True)
    main_power = result["h1a"]["power_20pct"]
    enough = [n for n in NS if main_power[n] >= 0.8]
    result["chosen_n"] = min(enough) if enough else 100
    result["rule"] = "smallest n with detection rate >= 0.8 on D = 0.01 data; else 100 (cap)"
    (OUT / "power.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# H1b Step 1: seeds per condition (from stored H1a runs; no simulation)", "",
             f"Method: `scripts/h1b_power.py`; {REPS} simulated experiments per n, {BOOT} bootstrap "
             "resamples each; 20% shorter tau for recovered hetero runs, censored runs unchanged.", "",
             "| Data | Pairs | Censored share | Paired diff median [IQR] | " + " | ".join(f"n={n}" for n in NS) + " |",
             "|---|---|---|---|" + "---|" * len(NS)]
    for step, label in (("h1a", "D = 0.01 (used)"), ("robust", "D = 0.02 (sensitivity)")):
        r = result[step]
        lines.append(f"| {label} | {r['n_pairs']} | {r['censored_share']:.2f} | "
                     f"{r['paired_diff_median']:,.0f} [{r['paired_diff_iqr'][0]:,.0f}, {r['paired_diff_iqr'][1]:,.0f}] | "
                     + " | ".join(f"{r['power_20pct'][n]:.2f}" for n in NS) + " |")
    lines += ["", "False detection rate with no effect: "
              + "; ".join(f"{s}: " + ", ".join(f"n={n} {v:.3f}" for n, v in result[s]["false_detection"].items())
                          for s in ("h1a", "robust")),
              "", f"**Chosen n = {result['chosen_n']}** ({result['rule']})."]
    (OUT / "power.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
