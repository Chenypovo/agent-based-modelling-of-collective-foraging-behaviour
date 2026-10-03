#!/usr/bin/env python3
"""Figures for results/paper_baseline/REPORT.md (line / dot plots only)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "paper_baseline"
FIG = OUT / "figures"
ARMS = {"base": ("Baseline (FCRW)", "#2a78d6"), "zw": ("ZW walk", "#eb6834"),
        "paperlayout": ("Paper layout (food 212 away)", "#1baf7a"), "a600": ("Arena 600 × 600", "#eda100")}
OFF = ("Baseline, pheromone off", "#8a8a85")
INK, MUTED, GRID = "#1f1f1e", "#6b6b66", "#e6e6e3"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "lines.linewidth": 2})


def runs(step: str, name: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((OUT / step / "runs").glob(f"{name}_2*.json"))]


def median_series(rs, key, smooth=10):
    """Median over seeds, then a centred running mean over ``smooth`` samples (10 samples = 100 steps)."""
    y = np.median(np.array([r["series"][key] for r in rs], dtype=float), axis=0)
    if smooth > 1:
        y = np.convolve(np.pad(y, smooth // 2, mode="edge"), np.ones(smooth) / smooth, mode="same")[smooth // 2:-(smooth // 2)]
    return y


def end_label(ax, x, y, text, color, dy=0.0):
    ax.annotate(text, (x, y), xytext=(6, dy), textcoords="offset points", va="center", fontsize=9, color=INK)
    ax.plot([x], [y], "o", color=color, ms=4)


def fig_order():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharex=True)
    data = {k: runs("valid", k) for k in ARMS}
    off = runs("valid", "base_off")
    t = np.array(off[0]["series"]["time"])
    for ax, key, title, line in ((axes[0], "psi", "Nematic order ψ (Eq. 17)", 0.9),
                                 (axes[1], "phi", "Orientation order φ, rad (Eq. 16)", math.pi / 4 - 0.1)):
        ax.axvspan(18000, 20000, color=GRID, alpha=0.6, lw=0)
        ax.axhline(line, color=MUTED, lw=1, ls=":")
        ax.text(200, line, f" pass line {line:.3f}", va="bottom", fontsize=8, color=MUTED)
        if key == "phi":
            ax.axhline(math.pi / 4, color=MUTED, lw=1, ls="--")
            ax.text(200, math.pi / 4, " target π/4", va="bottom", fontsize=8, color=MUTED)
        ax.plot(t, median_series(off, key), color=OFF[1], lw=1.5, ls="--", label=OFF[0])
        for k, (label, color) in ARMS.items():
            y = median_series(data[k], key)
            ax.plot(t, y, color=color, label=label)
        ax.set_title(title, loc="left", fontsize=10, color=INK)
        ax.set_xlabel("time step")
        ax.set_xlim(0, 20000)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, fontsize=8, frameon=False)
    fig.suptitle("Colony order over time (median of 20 seeds, 100-step running mean; grey band = measurement window)",
                 x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(FIG / "fig1_order_over_time.png", dpi=150)
    plt.close(fig)


def fig_roles():
    rs = runs("valid", "base")
    t = np.array(rs[0]["series"]["time"])
    fig, ax = plt.subplots(figsize=(7.5, 4))
    for key, label, color in (("F", "foragers (searching)", "#8a8a85"), ("T", "transporters", "#eb6834"),
                              ("f", "followers", "#2a78d6")):
        y = median_series(rs, key)
        ax.plot(t, y, color=color, label=label)
        end_label(ax, t[-1], y[-1], f"{label} {y[-1]:.0f}", color)
    ax.axhline(10, color=MUTED, lw=1, ls=":")
    ax.text(10500, 9, "foragers ≤ 10 (full pass)", va="top", fontsize=8, color=MUTED)
    ax.set_xlim(0, 24500)
    ax.set_xlabel("time step")
    ax.set_ylabel("number of ants (of 100)")
    ax.legend(loc="upper center", fontsize=8, frameon=False, ncol=3)
    ax.set_title("Baseline: task redistribution (median of 20 seeds)", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "fig2_roles_baseline.png", dpi=150)
    plt.close(fig)


def fig_snapshots(name="base", seed=2026300001, nest=(150, 150), food=(150 + 90 / 2 ** .5, 150 + 90 / 2 ** .5)):
    r = json.loads((OUT / "valid" / "runs" / f"{name}_{seed}.json").read_text())
    field = np.load(OUT / "valid" / "runs" / f"field_{name}_{seed}.npz")["c"]
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.9))
    style = {"fcrw": ("+", "#8a8a85", "forager"), "transporter": ("o", "#eb6834", "transporter"),
             "follower": ("x", "#2a78d6", "follower")}
    for ax, t in zip(axes, ("1000", "4000", "10000", "18000")):
        if t == "18000":
            ix, iy = np.nonzero(field >= 0.25)
            ax.scatter(ix + 0.5, iy + 0.5, s=1, color="#1baf7a", alpha=0.35, lw=0)
            ax.scatter([], [], s=30, marker="s", color="#1baf7a", alpha=0.6, label="pheromone ≥ on-threshold (0.25)")
        for role, (m, c, label) in style.items():
            pts = np.array([p[:2] for p in r["snapshots"][t] if p[2] == role] or np.empty((0, 2)))
            if len(pts):
                ax.scatter(pts[:, 0], pts[:, 1], marker=m, s=18, color=c, lw=1, label=label)
        ax.plot(*nest, "o", color=INK, ms=7)
        ax.plot(*food, "*", color=INK, ms=11)
        ax.set_xlim(0, 300)
        ax.set_ylim(0, 300)
        ax.set_aspect("equal")
        ax.set_title(f"t = {int(t):,}", loc="left", fontsize=10)
        ax.grid(False)
    axes[-1].legend(loc="upper left", fontsize=7, frameon=False, markerscale=1.2)
    fig.suptitle(f"Baseline, seed {seed}: ant positions by role (● nest, ★ food)", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(FIG / "fig3_snapshots_baseline.png", dpi=150)
    plt.close(fig)


def fig_phi_per_seed():
    fig, ax = plt.subplots(figsize=(8, 4))
    line = math.pi / 4 - 0.1
    for i, (k, (label, color)) in enumerate(ARMS.items()):
        phis = np.array([r["phi"] for r in runs("valid", k)])
        x = i + np.linspace(-0.18, 0.18, len(phis))
        ax.scatter(x, np.sort(phis), s=28, color=color, edgecolor="white", lw=1, zorder=3)
        ax.text(i, max(phis.max(), line) + 0.012, f"{(phis >= line).sum()}/20 with φ ≥ line", ha="center", fontsize=8)
    ax.axhline(line, color=MUTED, lw=1, ls=":")
    ax.text(2.5, line - 0.01, f"pass line {line:.3f}", va="top", ha="center", fontsize=8, color=MUTED)
    ax.set_xticks(range(len(ARMS)), [v[0] for v in ARMS.values()], fontsize=8)
    ax.set_ylabel("φ averaged over [18,000, 20,000)")
    ax.set_title("Check 5: φ per seed (16 of 20 seeds must reach the line)", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "fig4_phi_per_seed.png", dpi=150)
    plt.close(fig)


def fig_deliveries():
    fig, ax = plt.subplots(figsize=(7.5, 4))
    t = np.arange(0, 20001, 100)
    nudge = {"zw": 6, "base": -6, "paperlayout": 6, "a600": -6, "base_off": 0}
    for k, (label, color) in list(ARMS.items()) + [("base_off", OFF)]:
        rs = runs("valid", k)
        cum = np.median([np.searchsorted(np.sort(r["delivery_times"]), t, side="right") for r in rs], axis=0)
        ax.plot(t, cum, color=color, ls="--" if k == "base_off" else "-", lw=1.5 if k == "base_off" else 2)
        end_label(ax, t[-1], cum[-1], f"{label if k != 'base_off' else OFF[0]} {cum[-1]:.0f}", color, dy=nudge[k])
    ax.axvspan(14000, 20000, color=GRID, alpha=0.6, lw=0)
    ax.set_xlim(0, 27500)
    ax.set_xlabel("time step")
    ax.set_ylabel("cumulative deliveries")
    ax.set_title("Food delivered to the nest (median of 20 seeds; grey = check-4 window)", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "fig5_cumulative_deliveries.png", dpi=150)
    plt.close(fig)


def fig_steps():
    """Best-cell medians at each step: how far each model version got."""
    def best(step, key="psi"):
        s = json.loads((OUT / step / "summary.json").read_text())
        cells = {k: v for k, v in s.items() if not k.endswith("off")}
        k = max(cells, key=lambda c: cells[c]["medians"]["psi"])
        return cells[k]["medians"]
    stages = [("Step 2\npaper rules,\nno decay", best("paper")), ("Step 3\n+ Eq. (1) field\n(best of 18)", best("calib")),
              ("Step 3b\n+ home vector\n(best of 54)", best("calib2")), ("Step 3c\n20,000 steps\n(best of 54)", best("calib3")),
              ("Step 4\nvalidation\n(baseline)", json.loads((OUT / "valid" / "summary.json").read_text())["base"]["medians"])]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9))
    x = np.arange(len(stages))
    for ax, key, line, title in ((axes[0], "psi", 0.9, "ψ (pass ≥ 0.9; random = 0.64)"),
                                 (axes[1], "phi", math.pi / 4 - 0.1, "φ (pass ≥ 0.685)")):
        y = [m[key] for _, m in stages]
        ax.plot(x, y, color="#2a78d6", marker="o", ms=8)
        for xi, yi in zip(x, y):
            ax.annotate(f"{abs(yi) if abs(yi) < 0.005 else yi:.2f}", (xi, yi), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8)
        ax.axhline(line, color=MUTED, lw=1, ls=":")
        ax.set_xticks(x, [s for s, _ in stages], fontsize=7.5)
        ax.set_title(title, loc="left", fontsize=10)
    fig.suptitle("Best median order reached by each model version (late window of that step)", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(FIG / "fig6_progress_by_step.png", dpi=150)
    plt.close(fig)


def main() -> int:
    FIG.mkdir(parents=True, exist_ok=True)
    fig_order()
    fig_roles()
    fig_snapshots()
    fig_phi_per_seed()
    fig_deliveries()
    fig_steps()
    print("figures written to", FIG)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
