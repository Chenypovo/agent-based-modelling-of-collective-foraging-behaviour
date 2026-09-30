#!/usr/bin/env python3
"""Tables and figures for the Stage 5 homing-strategy comparison (exploratory)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import statistics as st
import sys

os.environ.setdefault("MPLBACKEND", "Agg")
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "stage5_diagnostics" / "navigation"

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LogNorm  # noqa: E402
import numpy as np  # noqa: E402

LABEL = {
    "retrace": "Exact retrace (current model)",
    "pi_0.0": "Path integration, no error",
    "pi_0.1": "Path integration, error 0.1",
    "pi_0.3": "Path integration, error 0.3",
    "pi_0.6": "Path integration, error 0.6",
    "pi_1.0": "Path integration, error 1.0",
    "pi_0.6_lm30": "Error 0.6 + 30 landmarks",
    "pi_0.6_lm300": "Error 0.6 + 300 landmarks",
    "pi_1.0_lm300": "Error 1.0 + 300 landmarks",
    "pi_0.0_sensor2": "No error, sensors 2 units out",
    "pi_0.1_sensor2": "Error 0.1, sensors 2 units out",
}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # validated categorical slots 1-4 (light)
INK, MUTED, GRID = "#222222", "#666666", "#e3e3e3"


def rows(experiment: str) -> list[dict]:
    path = OUT / experiment / "runs_summary.json"
    return json.loads(path.read_text()) if path.exists() else []


def med(values, fmt="{:.0f}"):
    v = [x for x in values if x is not None]
    if not v:
        return "-"
    return f"{fmt.format(st.median(v))} [{fmt.format(min(v))}-{fmt.format(max(v))}]"


def static_table(data: list[dict]) -> str:
    out = ["| Condition | Deliveries by 12000 | Median return trip (steps) | Unfinished trips at end "
           "| Local nest searches | Median homing error at arrival | Follower share of ant-steps | Pheromone direction bias R |",
           "|---|---|---|---|---|---|---|---|"]
    for name in LABEL:
        r = [x for x in data if x["condition"] == name]
        if not r:
            continue
        out.append("| " + " | ".join([
            LABEL[name], med([x["deliveries_A"] for x in r]), med([x["return_trip_median"] for x in r]),
            med([x["unfinished_trips"] for x in r]), med([x.get("search_starts") for x in r]),
            med([x.get("arrival_error_median") for x in r], "{:.1f}"),
            med([x["follower_fraction"] for x in r], "{:.3f}"),
            med([x["field_shape"]["bias_R"] for x in r], "{:.2f}")]) + " |")
    return "\n".join(out)


def relocation_table(data: list[dict]) -> str:
    out = ["| Condition | A deliveries 0-6000 | A deliveries 4800-6000 | B deliveries 6000-18000 "
           "| First B delivery after move (steps) | B deliveries 12000-18000 |",
           "|---|---|---|---|---|---|"]
    for name in LABEL:
        r = [x for x in data if x["condition"] == name]
        if not r:
            continue
        first = [(min(x["delivery_times_B"]) - 6000) if x["delivery_times_B"] else 12000 for x in r]
        out.append("| " + " | ".join([
            LABEL[name], med([x["deliveries_A"] for x in r]),
            med([sum(4800 <= t < 6000 for t in x["delivery_times_A"]) for x in r]),
            med([x["deliveries_B"] for x in r]), med(first) + f" ({sum(not x['delivery_times_B'] for x in r)} never)",
            med([sum(t >= 12000 for t in x["delivery_times_B"]) for x in r])]) + " |")
    return "\n".join(out)


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="x", color=GRID, lw=0.6)


def static_figure(data: list[dict]) -> Path:
    names = [n for n in LABEL if any(x["condition"] == n for x in data)]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True, sharey=True)
    metrics = [("deliveries_A", "Deliveries by t=12000"),
               ("arrival_error_median", "Homing error when it thinks it is home"),
               ("search_starts", "Returns needing a local nest search")]
    for ax, (key, title) in zip(axes, metrics):
        for i, n in enumerate(names):
            v = [x.get(key) for x in data if x["condition"] == n]
            v = [y for y in v if y is not None]
            if not v:
                ax.text(0, i, "n/a", va="center", fontsize=8, color=MUTED)
                continue
            ax.barh(i, st.median(v), color="#86b6ef", height=0.6)
            ax.plot(v, [i] * len(v), "o", color="#1c5cab", ms=3.5)
        ax.set_title(title, fontsize=10, loc="left", color=INK)
        _style(ax)
    axes[0].set_yticks(range(len(names)), [LABEL[n] for n in names])
    axes[0].invert_yaxis()
    fig.suptitle("Static food, 10 diagnostic seeds (bar = median, dots = seeds). Exploratory.",
                 fontsize=10, color=MUTED)
    path = OUT / "static_summary.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def maps_figure(experiment: str, seed: int, names: list[str]) -> Path:
    names = [n for n in names if (OUT / experiment / "runs" / n / f"{seed}.npz").exists()]
    fig, axes = plt.subplots(2, len(names), figsize=(3.2 * len(names), 6.6), constrained_layout=True)
    for j, n in enumerate(names):
        d = np.load(OUT / experiment / "runs" / n / f"{seed}.npz")
        r = next(x for x in rows(experiment) if x["condition"] == n and x["seed"] == seed)
        for i, (img, cmap, title) in enumerate(((d["mean_field"], "YlOrBr", "Mean pheromone"),
                                                (d["occupancy"], "Blues", "Where ants walked"))):
            ax = axes[i, j]
            img = np.asarray(img, float)
            pos = img[img > 0]
            if pos.size:
                ax.imshow(np.where(img > 0, img, np.nan).T, origin="lower", extent=[0, 300, 0, 300], cmap=cmap,
                          norm=LogNorm(vmin=max(pos.min(), pos.max() * 1e-3), vmax=pos.max()))
            ax.plot([150], [150], "o", color="#0d366b", ms=5)
            ax.plot([240], [150], "o", color="#8c2d04", ms=5)
            if experiment == "relocation":
                ax.plot([150], [240], "s", color="#8c2d04", ms=5, mfc="none")
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_xlim(0, 300)
            ax.set_ylim(0, 300)
            head = f"{LABEL[n]}\n" if i == 0 else ""
            deliveries = r["deliveries_A"] + r["deliveries_B"]
            ax.set_title(f"{head}{title}" + (f" | deliveries {deliveries}" if i == 0 else ""),
                         fontsize=8, loc="left", color=INK)
    fig.suptitle(f"{experiment.capitalize()}, diagnostic seed {seed}; nest dark blue, food A dark red"
                 + (", food B open square" if experiment == "relocation" else "") + ". Log colour scale.",
                 fontsize=9, color=MUTED)
    path = OUT / f"{experiment}_maps_seed{seed}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def relocation_figure(data: list[dict]) -> Path:
    names = [n for n in LABEL if any(x["condition"] == n for x in data)]
    grid = np.arange(0, 18001, 100)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), constrained_layout=True)
    for ax, source, title in ((axes[0], "A", "Cumulative food A deliveries (median of seeds)"),
                              (axes[1], "B", "Cumulative food B deliveries (median of seeds)")):
        for colour, n in zip(SERIES, names):
            r = [x for x in data if x["condition"] == n]
            curves = np.array([[sum(t <= g for t in x[f"delivery_times_{source}"]) for g in grid] for x in r])
            m = np.median(curves, axis=0)
            ax.plot(grid, m, color=colour, lw=2, label=LABEL[n])
            ax.text(grid[-1] + 150, m[-1], LABEL[n], fontsize=7, color=INK, va="center")
        ax.axvline(6000, color=MUTED, lw=1, ls="--")
        ax.text(6150, 0.5, "food moved", fontsize=8, color=MUTED, va="center", transform=ax.get_xaxis_transform())
        ax.set_title(title, fontsize=10, loc="left", color=INK)
        ax.set_xlabel("step", fontsize=8, color=MUTED)
        ax.set_xlim(0, 24500)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=MUTED, labelsize=8)
        ax.grid(axis="y", color=GRID, lw=0.6)
    axes[0].legend(fontsize=7, frameon=False, loc="upper left")
    fig.suptitle("Food relocation at step 6000, 10 diagnostic seeds. Exploratory.", fontsize=10, color=MUTED)
    path = OUT / "relocation_cumulative.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def terrain_outputs(data: list[dict]) -> tuple[str, Path]:
    noises = sorted({x["compass_noise"] for x in data})
    counts = sorted({x["landmarks"] for x in data})
    def grid(key):
        g = np.full((len(noises), len(counts)), np.nan)
        for i, n in enumerate(noises):
            for j, c in enumerate(counts):
                v = [x.get(key) for x in data if x["compass_noise"] == n and x["landmarks"] == c]
                v = [y for y in v if y is not None]
                if v:
                    g[i, j] = st.median(v)
        return g
    panels = [("deliveries_A", "Median deliveries by t=12000", "Blues", "{:.0f}"),
              ("arrival_error_median", "Median homing error when it thinks it is home", "Oranges", "{:.1f}")]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), constrained_layout=True)
    lines = []
    for ax, (key, title, cmap, fmt) in zip(axes, panels):
        g = grid(key)
        ax.imshow(g, cmap=cmap, aspect="auto")
        for i in range(len(noises)):
            for j in range(len(counts)):
                val = g[i, j]
                dark = val > np.nanmin(g) + 0.6 * (np.nanmax(g) - np.nanmin(g))
                ax.text(j, i, fmt.format(val), ha="center", va="center", fontsize=9,
                        color="white" if dark else INK)
        ax.set_xticks(range(len(counts)), [str(c) for c in counts])
        ax.set_yticks(range(len(noises)), [str(n) for n in noises])
        ax.set_xlabel("landmarks in arena (0 = open ground)", fontsize=8, color=MUTED)
        ax.set_ylabel("path-integration error per step", fontsize=8, color=MUTED)
        ax.set_title(title, fontsize=10, loc="left", color=INK)
        ax.tick_params(colors=MUTED, labelsize=8)
        header = "| error \\ landmarks | " + " | ".join(str(c) for c in counts) + " |"
        lines += [f"**{title}**", "", header, "|" + "---|" * (len(counts) + 1)]
        for i, n in enumerate(noises):
            cells = []
            for c in counts:
                v = [x.get(key) for x in data if x["compass_noise"] == n and x["landmarks"] == c]
                cells.append(med(v, fmt))
            lines.append(f"| {n} | " + " | ".join(cells) + " |")
        lines.append("")
    fig.suptitle("Terrain sweep, static food, 10 diagnostic seeds per cell. Exploratory.", fontsize=10, color=MUTED)
    path = OUT / "terrain_heatmaps.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return "\n".join(lines), path


def main() -> int:
    s, r = rows("static"), rows("relocation")
    text = []
    if s:
        text += ["## Static food", static_table(s)]
        print(static_figure(s))
        print(maps_figure("static", 2026093001, ["retrace", "pi_0.0", "pi_0.6", "pi_0.6_lm300", "pi_1.0", "pi_1.0_lm300"]))
    if r:
        text += ["## Food relocation", relocation_table(r)]
        print(relocation_figure(r))
        print(maps_figure("relocation", 2026093001, list(dict.fromkeys(x["condition"] for x in r))))
    terrain = rows("terrain")
    if terrain:
        md, fig = terrain_outputs(terrain)
        text += ["## Terrain sweep", md]
        print(fig)
    (OUT / "summary_tables.md").write_text("\n\n".join(text) + "\n")
    print("\n\n".join(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
