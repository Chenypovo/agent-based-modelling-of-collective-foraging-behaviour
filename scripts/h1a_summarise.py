#!/usr/bin/env python3
"""Summaries for the H1a runs, applying the rules in docs/H1A_ANALYSIS_PLAN.md exactly.

calib    -> calib/selection.json + calib/summary.md
ablation -> ablation/summary.md (+ adequacy verdict), ablation heatmaps
h1a      -> h1a/summary.md, h1a/stats.json (also 'robust')
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLBACKEND", "Agg")
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

from h1a_run import D_GRID, HALF_LIVES, LANDMARK_COUNTS, NOISES, OUT, THRESHOLDS  # noqa: E402

FOLLOWER_MIN, ARTEFACT_MAX, FALLBACK_BAND = 0.02, math.log(1.25), math.log(1.1)
BOOT, BOOT_SEED = 10000, 20261015
INTERMEDIATE, EXTREMES = (500, 1000, 2000), (250, 4000)


def load(step: str) -> list[dict]:
    return json.loads((OUT / step / "runs.json").read_text())


def by(rows, *keys):
    out = {}
    for r in rows:
        out.setdefault(tuple(r[k] for k in keys), []).append(r)
    return out


def med(values):
    values = [v for v in values if v is not None]
    return float(np.median(values)) if values else None


# ----- Step 2 --------------------------------------------------------------
def calib() -> None:
    rows = load("calib")
    cells = []
    for d in D_GRID:
        for on, off in THRESHOLDS:
            group = [r for r in rows if r["D"] == d and r["on"] == on]
            seeds = {c: {r["seed"]: r for r in group if r["name"].startswith(c)} for c in ("C1", "C2", "C3")}
            artefact = med([math.log((seeds["C2"][s]["deliveries_A"] + 1) / (seeds["C1"][s]["deliveries_A"] + 1))
                            for s in seeds["C1"]])
            follower = med([r["follower_fraction"] for r in seeds["C3"].values()])
            cells.append({"D": d, "on": on, "off": off, "follower_C3": follower, "artefact_A": artefact,
                          "rule1": follower >= FOLLOWER_MIN, "rule2": artefact <= ARTEFACT_MAX,
                          "rule3": d <= 0.25 and len(group) == 30,
                          **{f"deliveries_{c}": med([r["deliveries_A"] for r in seeds[c].values()])
                             for c in ("C1", "C2", "C3")},
                          **{f"follower_{c}": med([r["follower_fraction"] for r in seeds[c].values()])
                             for c in ("C1", "C2")}})
    chosen, method = None, None
    for on, _ in THRESHOLDS:
        passing = [c for c in cells if c["on"] == on and c["rule1"] and c["rule2"] and c["rule3"]]
        if passing:
            chosen = min(passing, key=lambda c: c["D"])
            method = "all rules, default thresholds" if on == THRESHOLDS[0][0] else "all rules, lower thresholds"
            break
    if chosen is None:
        gated = [c for c in cells if c["rule1"] and c["rule3"]]
        if gated:
            best = min(c["artefact_A"] for c in gated)
            band = [c for c in gated if c["artefact_A"] <= best + FALLBACK_BAND]
            order = [on for on, _ in THRESHOLDS]
            chosen = sorted(band, key=lambda c: (-c["follower_C3"], order.index(c["on"]), c["D"]))[0]
            method = "fallback: weakest artefact among recruiting cells, then highest follower fraction"
        else:
            chosen = max(cells, key=lambda c: c["follower_C3"])
            method = "fallback: NO cell recruits; highest follower fraction (flag to user)"
    i = D_GRID.index(chosen["D"])
    adjacent = [D_GRID[j] for j in (i - 1, i + 1) if 0 <= j < len(D_GRID)]
    rule1 = {c["D"]: c["rule1"] for c in cells if c["on"] == chosen["on"]}
    recruiting = [d for d in adjacent if rule1[d]]
    neighbour = max(recruiting) if recruiting else max(adjacent)
    selection = {"D": chosen["D"], "on": chosen["on"], "off": chosen["off"], "neighbour_D": neighbour,
                 "neighbour_recruits": rule1[neighbour], "method": method, "cells": cells}
    (OUT / "calib" / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    lines = ["# Step 2 calibration (exploratory; seeds 2026210001-10)", "",
             f"Chosen: D = {chosen['D']}, thresholds on {chosen['on']} / off {chosen['off']} ({method}).",
             f"Neighbouring D for Step 5: {neighbour} (recruits: {rule1[neighbour]}).", "",
             "Rule 1: median C3 follower fraction >= 0.02. Rule 2: A = median ln((C2+1)/(C1+1)) <= ln 1.25 = 0.223.",
             "", "| D | on/off | C1 del (err 0) | C2 del (err 0.1) | C3 del (baseline) | A | e^A | "
             "follower C1 / C2 / C3 | R1 | R2 | R3 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in cells:
        lines.append(f"| {c['D']} | {c['on']}/{c['off']} | {c['deliveries_C1']:.0f} | {c['deliveries_C2']:.0f} | "
                     f"{c['deliveries_C3']:.0f} | {c['artefact_A']:.3f} | {math.exp(c['artefact_A']):.2f} | "
                     f"{c['follower_C1']:.3f} / {c['follower_C2']:.3f} / {c['follower_C3']:.3f} | "
                     f"{'Y' if c['rule1'] else 'N'} | {'Y' if c['rule2'] else 'N'} | {'Y' if c['rule3'] else 'N'} |")
    (OUT / "calib" / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


# ----- Step 3 --------------------------------------------------------------
def ablation() -> None:
    import matplotlib.pyplot as plt

    rows = load("ablation")
    groups = by(rows, "name")
    retrace = med([r["deliveries_A"] for r in groups[("retrace",)]])
    base = groups[(f"pi_0.5_lm100",)]
    base_med = med([r["deliveries_A"] for r in base])
    base_min = min(r["deliveries_A"] for r in base)
    adequate = base_med >= 5 * retrace and base_min >= 20
    lines = ["# Step 3 navigation ablation (exploratory; seeds 2026230001-20)", "",
             f"Exact retrace median deliveries: {retrace:.0f}. Baseline (error 0.5, 100 landmarks): "
             f"median {base_med:.0f}, minimum {base_min}.",
             f"Adequacy (median >= 5x retrace and every seed >= 20): **{'PASS' if adequate else 'FAIL'}**.", ""]
    tables = {"deliveries": "deliveries_A", "arrival error (median)": "arrival_error_median",
              "follower fraction": "follower_fraction", "return trip (steps)": "return_trip_median"}
    grids = {}
    for title, key in tables.items():
        grid = np.array([[med([r[key] for r in groups[(f"pi_{n}_lm{lm}",)]]) or np.nan
                          for lm in LANDMARK_COUNTS] for n in NOISES], dtype=float)
        grids[title] = grid
        lines += [f"## Median {title}", "", "| error \\ landmarks | " + " | ".join(map(str, LANDMARK_COUNTS)) + " |",
                  "|---" * (len(LANDMARK_COUNTS) + 1) + "|"]
        for n, row in zip(NOISES, grid):
            lines.append(f"| {n} | " + " | ".join(f"{v:.3g}" for v in row) + " |")
        lines.append("")
    spread = grids["deliveries"].max(axis=0) / np.maximum(grids["deliveries"].min(axis=0), 1)
    lines += ["## Sensitivity to path-integration error (max/min median deliveries across errors)", "",
              "| landmarks | " + " | ".join(map(str, LANDMARK_COUNTS)) + " |", "|---" * 6 + "|",
              "| max/min | " + " | ".join(f"{v:.2f}" for v in spread) + " |", ""]
    (OUT / "ablation" / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, title, cmap in zip(axes, ("deliveries", "arrival error (median)"), ("viridis", "magma_r")):
        im = ax.imshow(grids[title], cmap=cmap, aspect="auto")
        ax.set(xticks=range(len(LANDMARK_COUNTS)), xticklabels=LANDMARK_COUNTS, yticks=range(len(NOISES)),
               yticklabels=NOISES, xlabel="landmarks", ylabel="path-integration error (rad/step)",
               title=f"median {title}")
        for (i, j), v in np.ndenumerate(grids[title]):
            ax.text(j, i, f"{v:.0f}" if title == "deliveries" else f"{v:.1f}", ha="center", va="center",
                    color="w", fontsize=8)
        fig.colorbar(im, ax=ax)
    fig.suptitle(f"Navigation ablation, 20 seeds (exact retrace median = {retrace:.0f})")
    fig.tight_layout()
    fig.savefig(OUT / "ablation" / "ablation_heatmap.png", dpi=150)


# ----- Steps 4 / 5 ---------------------------------------------------------
def recovery(step: str) -> None:
    import matplotlib.pyplot as plt

    rows = load(step)
    seeds = sorted({r["seed"] for r in rows})
    table = {h: {r["seed"]: r for r in rows if r["half_life"] == h} for h in HALF_LIVES}
    tau = {h: np.array([table[h][s]["tau"] for s in seeds], float) for h in HALF_LIVES}
    eff = {h: np.array([table[h][s]["deliveries_A_pre"] for s in seeds], float) for h in HALF_LIVES}
    ok = eff[1000] > 0
    rng = np.random.default_rng(BOOT_SEED)
    idx = rng.integers(0, len(seeds), size=(BOOT, len(seeds)))
    stats = {"seeds": seeds, "excluded_ratio_seeds": int((~ok).sum()), "per_half_life": {}, "comparisons": []}
    for h in HALF_LIVES:
        ratio = eff[h][ok] / eff[1000][ok]
        boot_ratio = np.median(ratio[rng.integers(0, len(ratio), size=(BOOT, len(ratio)))], axis=1)
        stats["per_half_life"][h] = {
            "median_tau": float(np.median(tau[h])),
            "non_recovery": int(sum(table[h][s]["non_recovery"] for s in seeds)),
            "non_recovery_R_pre_0": int(sum(table[h][s]["R_pre"] == 0 for s in seeds)),
            "median_R_pre": float(np.median([table[h][s]["R_pre"] for s in seeds])),
            "median_static_deliveries": float(np.median(eff[h])),
            "median_efficiency_ratio": float(np.median(ratio)),
            "ratio_ci": [float(np.percentile(boot_ratio, 2.5)), float(np.percentile(boot_ratio, 97.5))],
            "median_follower_fraction": float(np.median([table[h][s]["follower_fraction"] for s in seeds])),
            "tau_by_seed": tau[h].tolist()}
    for i in INTERMEDIATE:
        for e in EXTREMES:
            boot = np.median(tau[i][idx], axis=1) - np.median(tau[e][idx], axis=1)
            stats["comparisons"].append({"intermediate": i, "extreme": e,
                                         "delta": float(np.median(tau[i]) - np.median(tau[e])),
                                         "ci": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]})
    (OUT / step / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    label = "main result" if step == "h1a" else "robustness, exploratory"
    lines = [f"# {step} ({label}; seeds {seeds[0]}-{seeds[-1]}, D = {rows[0]['D']}, "
             f"thresholds {rows[0]['on']}/{rows[0]['off']})", "",
             "| half-life | median tau | non-recovery (of which R_pre=0) | median R_pre | median A deliveries "
             "[0,12000) | efficiency ratio vs 1000 [95% CI] | follower fraction |", "|---|---|---|---|---|---|---|"]
    for h, p in stats["per_half_life"].items():
        lines.append(f"| {h} | {p['median_tau']:.0f} | {p['non_recovery']} ({p['non_recovery_R_pre_0']}) | "
                     f"{p['median_R_pre']:.0f} | {p['median_static_deliveries']:.0f} | "
                     f"{p['median_efficiency_ratio']:.2f} [{p['ratio_ci'][0]:.2f}, {p['ratio_ci'][1]:.2f}] | "
                     f"{p['median_follower_fraction']:.3f} |")
    lines += ["", f"Seeds excluded from efficiency ratio (zero deliveries at half-life 1000): "
              f"{stats['excluded_ratio_seeds']}", "",
              "Paired bootstrap (10,000 resamples) of delta = median tau(intermediate) - median tau(extreme):", "",
              "| intermediate | extreme | delta | 95% CI |", "|---|---|---|---|"]
    for c in stats["comparisons"]:
        lines.append(f"| {c['intermediate']} | {c['extreme']} | {c['delta']:.0f} | [{c['ci'][0]:.0f}, {c['ci'][1]:.0f}] |")
    (OUT / step / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    x = np.arange(len(HALF_LIVES))
    for k, h in enumerate(HALF_LIVES):
        axes[0].scatter(np.full(len(seeds), k) + np.linspace(-0.15, 0.15, len(seeds)), tau[h], s=10, alpha=0.5)
    axes[0].plot(x, [np.median(tau[h]) for h in HALF_LIVES], "k-o", label="median")
    axes[0].axhline(24000, ls=":", c="grey", label="non-recovery (24,000)")
    axes[0].set(xticks=x, xticklabels=HALF_LIVES, xlabel="half-life (steps)", ylabel="recovery time tau (steps)",
                title="Recovery after food relocation")
    axes[0].legend(fontsize=8)
    p = stats["per_half_life"]
    axes[1].errorbar(x, [p[h]["median_efficiency_ratio"] for h in HALF_LIVES],
                     yerr=np.array([[p[h]["median_efficiency_ratio"] - p[h]["ratio_ci"][0],
                                     p[h]["ratio_ci"][1] - p[h]["median_efficiency_ratio"]] for h in HALF_LIVES]).T,
                     fmt="o-", capsize=3)
    axes[1].axhline(0.8, ls=":", c="grey", label="80% of half-life 1000")
    axes[1].set(xticks=x, xticklabels=HALF_LIVES, xlabel="half-life (steps)",
                ylabel="static deliveries / half-life 1000", title="Static efficiency (median, 95% CI)")
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / step / "recovery_efficiency.png", dpi=150)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("calib", "ablation", "h1a", "robust"))
    step = parser.parse_args().step
    {"calib": calib, "ablation": ablation}.get(step, lambda: recovery(step))()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
