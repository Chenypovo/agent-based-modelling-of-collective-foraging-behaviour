#!/usr/bin/env python3
"""Stage 5 exploratory diagnosis of the non-radial pheromone field (supervisor question on slide 3).

Static food A only (no relocation). Diagnostic seeds only; not confirmatory evidence.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("MPLBACKEND", "Agg")
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from scalar_baseline.config import DecayConfig, SimulationConfig  # noqa: E402
from stage5_navigation.model import CoarseReturnSimulation  # noqa: E402

SEEDS = tuple(range(2026093001, 2026093006))
STEPS = 24000
CHECKPOINTS = (6000, 12000, 24000)
OUT = ROOT / "results" / "stage5_diagnostics" / "field_shape"

# name: (arena_size, cell_size, waypoint_spacing)
CONDITIONS = {
    "current": (300, 1, 1),
    "cell2": (300, 2, 1),
    "cell3": (300, 3, 1),
    "arena600": (600, 1, 1),
    "coarse10": (300, 1, 10),
    "coarse50": (300, 1, 50),
    "straight": (300, 1, None),
}


def make_config(arena: float, cell: float, seed: int) -> SimulationConfig:
    c = arena / 2
    return SimulationConfig(n_ants=100, steps=STEPS, seed=seed, arena_size=arena, cell_size=cell,
                            nest=(c, c), food_a=(c + 90, c), food_b=(c, c + 90),
                            step_size=0.6, deposit_q=1, contact_radius=0.75, diffusion=0,
                            decay=DecayConfig(half_life_steps=1000), relocation_step=None)


def shape_metrics(weights: np.ndarray, centres_x: np.ndarray, centres_y: np.ndarray,
                  nest: tuple[float, float]) -> dict:
    """Directional bias of a mass map around the nest: R=0 even in all directions, R=1 one direction."""
    dx, dy = centres_x - nest[0], centres_y - nest[1]
    r = np.hypot(dx, dy)
    mask = r > 1e-9
    w = np.where(mask, weights, 0.0)
    total = float(w.sum())
    if total <= 0:
        return {"mass": 0.0, "bias_R": None, "bias_direction_deg": None,
                "quadrant_share": None, "near_nest_share": None}
    ang = np.arctan2(dy, dx)
    cx, cy = float((w * np.cos(ang)).sum() / total), float((w * np.sin(ang)).sum() / total)
    quads = {
        "right_up": float(w[(dx >= 0) & (dy >= 0)].sum() / total),
        "left_up": float(w[(dx < 0) & (dy >= 0)].sum() / total),
        "left_down": float(w[(dx < 0) & (dy < 0)].sum() / total),
        "right_down": float(w[(dx >= 0) & (dy < 0)].sum() / total),
    }
    return {"mass": total, "bias_R": math.hypot(cx, cy),
            "bias_direction_deg": math.degrees(math.atan2(cy, cx)) % 360,
            "quadrant_share": quads, "near_nest_share": float(w[r <= 20].sum() / total)}


def run_one(task: tuple[str, int]) -> dict:
    name, seed = task
    arena, cell, spacing = CONDITIONS[name]
    config = make_config(arena, cell, seed)
    sim = CoarseReturnSimulation(config, waypoint_spacing=spacing)
    n = sim.field.concentration.shape[0]
    centres = (np.arange(n) + 0.5) * cell
    fx, fy = np.meshgrid(centres, centres, indexing="ij")  # field index is [x, y]
    bins = 60
    occ = np.zeros((bins, bins))
    field_sum = np.zeros_like(sim.field.concentration)
    samples = 0
    snapshots, checkpoint = {}, {}
    pickups: dict[int, int] = {}
    trip_steps, follower_steps = [], 0
    start = time.perf_counter()
    while sim.time < STEPS:
        before = {a.ant_id: a.role for a in sim.ants}
        n_events = len(sim.ledger.events)
        sim.step()
        for e in sim.ledger.events[n_events:]:
            if e["event"] == "pickup":
                pickups[e["ant_id"]] = e["time"]
            elif e["event"] == "delivery":
                trip_steps.append(e["time"] - pickups.pop(e["ant_id"]))
        follower_steps += sum(a.role == "follower" for a in sim.ants)
        if sim.time % 10 == 0:
            xy = np.array([a.position for a in sim.ants])
            h, _, _ = np.histogram2d(xy[:, 0], xy[:, 1], bins=bins, range=[[0, arena], [0, arena]])
            occ += h
        if sim.time % 100 == 0:
            field_sum += sim.field.concentration
            samples += 1
        if sim.time in CHECKPOINTS:
            mean_field = field_sum / samples
            snapshots[f"field_t{sim.time}"] = sim.field.concentration.copy()
            snapshots[f"meanfield_t{sim.time}"] = mean_field
            snapshots[f"occupancy_t{sim.time}"] = occ.copy()
            oc = (np.arange(bins) + 0.5) * arena / bins
            ox, oy = np.meshgrid(oc, oc, indexing="ij")
            checkpoint[str(sim.time)] = {
                "deliveries": sim.ledger.deliveries["A"],
                "field_final": shape_metrics(sim.field.concentration, fx, fy, config.nest),
                "field_time_mean": shape_metrics(mean_field, fx, fy, config.nest),
                "occupancy": shape_metrics(occ, ox, oy, config.nest),
            }
    run_dir = OUT / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(run_dir / f"{seed}.npz", **snapshots)
    deliveries = [e["time"] for e in sim.ledger.events if e["event"] == "delivery"]
    return {"condition": name, "seed": seed, "arena": arena, "cell": cell,
            "waypoint_spacing": spacing, "steps": STEPS, "checkpoints": checkpoint,
            "first_delivery": deliveries[0] if deliveries else None,
            "return_trip_steps_median": float(np.median(trip_steps)) if trip_steps else None,
            "return_trip_steps_mean": float(np.mean(trip_steps)) if trip_steps else None,
            "completed_trips": len(trip_steps),
            "follower_fraction": follower_steps / (STEPS * config.n_ants),
            "wall_seconds": time.perf_counter() - start}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--conditions", nargs="*", default=list(CONDITIONS))
    args = parser.parse_args()
    tasks = [(c, s) for c in args.conditions for s in SEEDS]
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for r in pool.map(run_one, tasks):
            results.append(r)
            cp = r["checkpoints"]["12000"]
            print(json.dumps({"condition": r["condition"], "seed": r["seed"],
                              "deliveries_12000": cp["deliveries"],
                              "wall": round(r["wall_seconds"], 1)}), flush=True)
    summary_path = OUT / "runs_summary.json"
    old = json.loads(summary_path.read_text()) if summary_path.exists() else []
    keep = [x for x in old if (x["condition"], x["seed"]) not in set(tasks)]
    summary_path.write_text(json.dumps(keep + results, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
