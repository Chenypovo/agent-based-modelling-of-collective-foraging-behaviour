#!/usr/bin/env python3
"""Summaries for the H1b runs, applying docs/H1B_ANALYSIS_PLAN.md exactly.

main / robust -> <step>/stats.json, summary.md, recovery_efficiency.png (verdict rule applied)
sweep         -> sweep/summary.md (exploratory; compares against the main-step homo/het120 runs)
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

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from h1b_run import OUT, RELOCATION, SEEDS  # noqa: E402

BOOT, BOOT_SEED, CENSOR, EARLY_END, EFF_MIN = 10000, 20261007, 24000, 18000, 0.8


def load(step: str) -> dict[str, dict[int, dict]]:
    rows = json.loads((OUT / step / "runs.json").read_text())
    out: dict[str, dict[int, dict]] = {}
    for r in rows:
        out.setdefault(r["name"], {})[r["seed"]] = r
    return out


def first_b(r: dict) -> float:
    return min((t - RELOCATION for t in r["delivery_times_B"] if t >= RELOCATION), default=math.nan)


def early_b(r: dict) -> int:
    return sum(RELOCATION <= t < EARLY_END for t in r["delivery_times_B"])


def compare(base: dict[int, dict], other: dict[int, dict], seeds: list[int]) -> dict:
    """Paired bootstrap of median tau difference and efficiency ratio (other vs base)."""
    tau_b = np.array([base[s]["tau"] for s in seeds], float)
    tau_o = np.array([other[s]["tau"] for s in seeds], float)
    eff_b = np.array([base[s]["deliveries_A_pre"] for s in seeds], float)
    eff_o = np.array([other[s]["deliveries_A_pre"] for s in seeds], float)
    ok = eff_b > 0
    ratio = eff_o[ok] / eff_b[ok]
    rng = np.random.default_rng(BOOT_SEED)
    idx = rng.integers(0, len(seeds), size=(BOOT, len(seeds)))
    boot = np.median(tau_o[idx], axis=1) - np.median(tau_b[idx], axis=1)
    boot_ratio = np.median(ratio[rng.integers(0, len(ratio), size=(BOOT, len(ratio)))], axis=1)
    return {"delta": float(np.median(tau_o) - np.median(tau_b)),
            "ci": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
            "efficiency_ratio": float(np.median(ratio)),
            "ratio_ci": [float(np.percentile(boot_ratio, 2.5)), float(np.percentile(boot_ratio, 97.5))],
            "excluded_ratio_seeds": int((~ok).sum()),
            "paired_tau_diff_iqr": [float(np.percentile(tau_o - tau_b, q)) for q in (25, 50, 75)]}


def describe(runs: dict[int, dict], seeds: list[int]) -> dict:
    rs = [runs[s] for s in seeds]
    q = lambda x: [float(np.nanpercentile(x, p)) for p in (25, 50, 75)]  # noqa: E731
    by_group = {g: {src: int(sum(r["pickups_by_group"][g][src] for r in rs)) for src in ("A", "B")}
                for g in ("scout", "recruit")}
    return {"median_tau": float(np.median([r["tau"] for r in rs])),
            "non_recovery": int(sum(r["non_recovery"] for r in rs)),
            "non_recovery_R_pre_0": int(sum(r["R_pre"] == 0 for r in rs)),
            "median_R_pre": float(np.median([r["R_pre"] for r in rs])),
            "median_static_deliveries": float(np.median([r["deliveries_A_pre"] for r in rs])),
            "median_follower_fraction": float(np.median([r["follower_fraction"] for r in rs])),
            "first_B_quartiles": q([first_b(r) for r in rs]), "no_B_delivery": int(sum(not r["delivery_times_B"] for r in rs)),
            "early_B_quartiles": q([early_b(r) for r in rs]),
            "pickups_by_group": by_group,
            "first_B_pickup_by_scout": int(sum(r["first_B_pickup_group"] == "scout" for r in rs))}


def recovery(step: str) -> None:
    runs = load(step)
    seeds = sorted(SEEDS[step])
    assert all(set(runs[c]) == set(seeds) for c in ("homo", "het120")), "missing runs"
    homo, het = runs["homo"], runs["het120"]
    stats = {"seeds": [seeds[0], seeds[-1], len(seeds)], "D": homo[seeds[0]]["D"],
             "theta_deg": {c: [math.degrees(runs[c][seeds[0]]["theta_scout"]),
                               math.degrees(runs[c][seeds[0]]["theta_recruit"])] for c in ("homo", "het120")},
             "per_condition": {c: describe(runs[c], seeds) for c in ("homo", "het120")},
             "comparison": compare(homo, het, seeds),
             "secondary_paired_median_diff": {
                 "first_B": float(np.nanmedian([first_b(het[s]) - first_b(homo[s]) for s in seeds])),
                 "early_B": float(np.median([early_b(het[s]) - early_b(homo[s]) for s in seeds]))}}
    c, p = stats["comparison"], stats["per_condition"]
    rule = {"a_median_shorter": p["het120"]["median_tau"] < p["homo"]["median_tau"],
            "b_ci_excludes_0": c["ci"][1] < 0 or c["ci"][0] > 0,
            "c_efficiency_ratio_ge_0.8": c["efficiency_ratio"] >= EFF_MIN}
    stats["rule"] = rule
    stats["verdict"] = "supported" if all(rule.values()) else "not supported"
    (OUT / step / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    label = "main result" if step == "main" else "robustness, exploratory"
    fq = lambda x: f"{x[1]:,.0f} [{x[0]:,.0f}, {x[2]:,.0f}]"  # noqa: E731
    lines = [f"# H1b {step} ({label}; seeds {seeds[0]}-{seeds[-1]}, n = {len(seeds)}, D = {stats['D']})", "",
             "| Condition | median τ | non-recovery (R_pre = 0) | median R_pre | median A deliveries [0, 12,000) "
             "| follower fraction | first B delivery after move, median [IQR] | B deliveries [12,000, 18,000) |",
             "|---|---|---|---|---|---|---|---|"]
    for name, label_c in (("homo", "homo (100 × 60°)"), ("het120", "het120 (20 × 120° + 80 × 37.43°)")):
        d = p[name]
        lines.append(f"| {label_c} | {d['median_tau']:,.0f} | {d['non_recovery']} ({d['non_recovery_R_pre_0']}) | "
                     f"{d['median_R_pre']:.0f} | {d['median_static_deliveries']:.0f} | "
                     f"{d['median_follower_fraction']:.3f} | {fq(d['first_B_quartiles'])} | {fq(d['early_B_quartiles'])} |")
    lines += ["", f"Δ = median τ(het120) − median τ(homo) = **{c['delta']:,.0f}** steps, paired bootstrap 95% CI "
              f"[{c['ci'][0]:,.0f}, {c['ci'][1]:,.0f}] ({BOOT:,} resamples). Per-seed paired τ difference, "
              f"median [IQR]: {c['paired_tau_diff_iqr'][1]:,.0f} [{c['paired_tau_diff_iqr'][0]:,.0f}, "
              f"{c['paired_tau_diff_iqr'][2]:,.0f}].",
              f"Static efficiency ratio het120 / homo: median **{c['efficiency_ratio']:.2f}** "
              f"[{c['ratio_ci'][0]:.2f}, {c['ratio_ci'][1]:.2f}] (seeds excluded for zero homo deliveries: "
              f"{c['excluded_ratio_seeds']}).", "",
              f"Verdict rule: (a) median shorter {rule['a_median_shorter']}; (b) CI excludes 0 {rule['b_ci_excludes_0']}; "
              f"(c) efficiency ratio ≥ 0.8 {rule['c_efficiency_ratio_ge_0.8']} → **{stats['verdict']}**.", "",
              "Secondary, descriptive (not used for the verdict): paired median difference het120 − homo in "
              f"time to first B delivery {stats['secondary_paired_median_diff']['first_B']:,.0f} steps; in B deliveries "
              f"[12,000, 18,000) {stats['secondary_paired_median_diff']['early_B']:,.0f}.",
              f"het120 pickups by group (all seeds, A / B): scouts {p['het120']['pickups_by_group']['scout']['A']} / "
              f"{p['het120']['pickups_by_group']['scout']['B']}, recruits {p['het120']['pickups_by_group']['recruit']['A']} / "
              f"{p['het120']['pickups_by_group']['recruit']['B']}; first B pickup by a scout in "
              f"{p['het120']['first_B_pickup_by_scout']} of {len(seeds)} seeds (scouts are 20% of ants)."]
    (OUT / step / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    tau = {k: np.array([runs[k][s]["tau"] for s in seeds], float) for k in ("homo", "het120")}
    for k, name in enumerate(("homo", "het120")):
        jitter = np.random.default_rng(k).uniform(-0.15, 0.15, len(seeds))
        axes[0].scatter(k + jitter, tau[name], s=6, alpha=0.4)
        axes[0].plot([k - 0.25, k + 0.25], [np.median(tau[name])] * 2, "k-", lw=2)
    axes[0].axhline(CENSOR, ls=":", c="grey", label="non-recovery (24,000)")
    axes[0].set(xticks=[0, 1], xticklabels=["homo 60°", "het 120°/37.4°"], ylabel="recovery time τ (steps)",
                title=f"Recovery after relocation (black = median), n = {len(seeds)}")
    axes[0].legend(fontsize=8)
    diff = tau["het120"] - tau["homo"]
    axes[1].hist(diff, bins=40, color="0.5")
    axes[1].axvline(0, c="k", lw=1)
    axes[1].set(xlabel="τ(het120) − τ(homo) per seed (steps)", ylabel="seeds", title="Paired differences")
    fig.tight_layout()
    fig.savefig(OUT / step / "recovery_efficiency.png", dpi=150)


def sweep() -> None:
    main_runs, extra = load("main"), load("sweep")
    seeds = sorted(SEEDS["sweep"])
    homo = main_runs["homo"]
    conds = [("het80", extra), ("het100", extra), ("het120", main_runs), ("homo_straight", extra)]
    lines = [f"# H1b sweep (exploratory; first {len(seeds)} main seeds, D = 0.01; vs homo 60° on the same seeds)", "",
             "| Condition | θ scout / recruit (deg) | median τ | non-recovery | Δ vs homo [95% CI] | efficiency ratio [95% CI] |",
             "|---|---|---|---|---|---|",
             f"| homo | 60 / 60 | {np.median([homo[s]['tau'] for s in seeds]):,.0f} | "
             f"{sum(homo[s]['non_recovery'] for s in seeds)} | — | 1.00 |"]
    stats = {}
    for name, src in conds:
        runs = src[name]
        c = compare(homo, runs, seeds)
        stats[name] = c
        r0 = runs[seeds[0]]
        lines.append(f"| {name} | {math.degrees(r0['theta_scout']):.1f} / {math.degrees(r0['theta_recruit']):.1f} | "
                     f"{np.median([runs[s]['tau'] for s in seeds]):,.0f} | {sum(runs[s]['non_recovery'] for s in seeds)} | "
                     f"{c['delta']:,.0f} [{c['ci'][0]:,.0f}, {c['ci'][1]:,.0f}] | "
                     f"{c['efficiency_ratio']:.2f} [{c['ratio_ci'][0]:.2f}, {c['ratio_ci'][1]:.2f}] |")
    (OUT / "sweep" / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    (OUT / "sweep" / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("main", "robust", "sweep"))
    step = parser.parse_args().step
    sweep() if step == "sweep" else recovery(step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
