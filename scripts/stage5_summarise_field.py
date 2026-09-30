#!/usr/bin/env python3
"""Figures and table for the Stage 5 field-shape diagnosis (exploratory, diagnostic seeds)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import statistics as st
import sys

os.environ.setdefault("MPLBACKEND", "Agg")
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "stage5_diagnostics" / "field_shape"

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LogNorm  # noqa: E402
import numpy as np  # noqa: E402

ORDER = ["current", "cell2", "cell3", "arena600", "coarse10", "coarse50", "straight"]
LABEL = {"current": "Current (300, cell 1, exact retrace)", "cell2": "Cell size 2",
         "cell3": "Cell size 3", "arena600": "Arena 600",
         "coarse10": "Coarse return, every 10th point", "coarse50": "Coarse return, every 50th point",
         "straight": "Straight home (path integration)"}


def load() -> list[dict]:
    return json.loads((OUT / "runs_summary.json").read_text())


def table(rows: list[dict]) -> str:
    def cell(values, fmt="{:.0f}"):
        values = [v for v in values if v is not None]
        if not values:
            return "-"
        return f"{fmt.format(st.median(values))} [{fmt.format(min(values))}-{fmt.format(max(values))}]"

    lines = ["| Condition | Deliveries by 6000 | by 12000 | by 24000 | Median return trip (steps) "
             "| Pheromone bias R (0-12000 mean) | Ant occupancy bias R | Pheromone share lower-left | Occupancy share lower-left |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name in ORDER:
        r = [x for x in rows if x["condition"] == name]
        if not r:
            continue
        cp = lambda t, *keys: [_get(x["checkpoints"][t], keys) for x in r]  # noqa: E731
        lines.append("| " + " | ".join([
            LABEL[name],
            cell(cp("6000", "deliveries")), cell(cp("12000", "deliveries")), cell(cp("24000", "deliveries")),
            cell([x["return_trip_steps_median"] for x in r]),
            cell(cp("12000", "field_time_mean", "bias_R"), "{:.2f}"),
            cell(cp("12000", "occupancy", "bias_R"), "{:.2f}"),
            cell(cp("12000", "field_time_mean", "quadrant_share", "left_down"), "{:.2f}"),
            cell(cp("12000", "occupancy", "quadrant_share", "left_down"), "{:.2f}"),
        ]) + " |")
    return "\n".join(lines)


def _get(d, keys):
    for k in keys:
        if d is None:
            return None
        d = d[k]
    return d


def maps(rows: list[dict], seed: int, t: int) -> Path:
    names = [n for n in ORDER if (OUT / "runs" / n / f"{seed}.npz").exists()]
    fig, axes = plt.subplots(len(names), 3, figsize=(11, 3.2 * len(names)), constrained_layout=True)
    for i, name in enumerate(names):
        r = next(x for x in rows if x["condition"] == name and x["seed"] == seed)
        data = np.load(OUT / "runs" / name / f"{seed}.npz")
        arena, c = r["arena"], r["arena"] / 2
        ext = [0, arena, 0, arena]
        panels = [(data[f"meanfield_t{t}"], f"Mean pheromone 0-{t}", "YlOrBr", True),
                  (data[f"field_t{t}"], f"Pheromone at t={t}", "YlOrBr", True),
                  (data[f"occupancy_t{t}"], f"Where all ants walked 0-{t}", "Blues", True)]
        for j, (img, title, cmap, log) in enumerate(panels):
            ax = axes[i, j]
            img = np.asarray(img, dtype=float)
            positive = img[img > 0]
            if positive.size:
                norm = LogNorm(vmin=max(positive.min(), positive.max() * 1e-3), vmax=positive.max())
                ax.imshow(np.where(img > 0, img, np.nan).T, origin="lower", extent=ext, cmap=cmap, norm=norm)
            ax.plot([c], [c], "o", color="#1f3b73", ms=5)
            ax.plot([c + 90], [c], "o", color="#8c2d04", ms=5)
            ax.set_xlim(0, arena)
            ax.set_ylim(0, arena)
            ax.set_xticks([])
            ax.set_yticks([])
            d = r["checkpoints"][str(t)]
            ax.set_title(f"{title}\n{LABEL[name]}" if j == 0 else title, fontsize=9, loc="left")
            if j == 0:
                ax.set_ylabel(f"deliveries by {t}: {d['deliveries']}", fontsize=9)
    fig.suptitle(f"Diagnostic seed {seed}: nest (dark blue), food A (dark red). Log colour scale. "
                 "Exploratory; not confirmatory.", fontsize=10)
    path = OUT / f"field_maps_seed{seed}_t{t}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def bars(rows: list[dict]) -> Path:
    names = [n for n in ORDER if any(x["condition"] == n for x in rows)]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), constrained_layout=True)
    for ax, key, title in ((axes[0], "deliveries", "Deliveries by t=12000 (5 seeds)"),
                           (axes[1], "bias", "Direction bias R, 0 = even, 1 = one direction")):
        for i, name in enumerate(names):
            r = [x for x in rows if x["condition"] == name]
            if key == "deliveries":
                v = [x["checkpoints"]["12000"]["deliveries"] for x in r]
                ax.barh(i, st.median(v), color="#6b8fb3", height=0.6)
                ax.plot(v, [i] * len(v), "o", color="#1f3b73", ms=4)
            else:
                ph = [x["checkpoints"]["12000"]["field_time_mean"]["bias_R"] for x in r]
                oc = [x["checkpoints"]["12000"]["occupancy"]["bias_R"] for x in r]
                ax.plot(ph, [i + 0.12] * len(ph), "o", color="#8c2d04", ms=5,
                        label="pheromone" if i == 0 else None)
                ax.plot(oc, [i - 0.12] * len(oc), "s", color="#1f3b73", ms=5,
                        label="ant occupancy" if i == 0 else None)
                ax.set_xlim(0, 1)
        ax.set_yticks(range(len(names)), [LABEL[n] for n in names], fontsize=8)
        ax.invert_yaxis()
        ax.set_title(title, fontsize=10, loc="left")
        ax.grid(axis="x", color="#dddddd", lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[1].legend(fontsize=8, frameon=False, loc="lower right")
    path = OUT / "summary_deliveries_bias.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def main() -> int:
    rows = load()
    md = table(rows)
    (OUT / "summary_table.md").write_text(md + "\n")
    print(md)
    print(maps(rows, 2026093001, 12000))
    print(bars(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
