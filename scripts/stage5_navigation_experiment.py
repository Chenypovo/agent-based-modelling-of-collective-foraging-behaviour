#!/usr/bin/env python3
"""Stage 5 exploratory comparison of homing strategies (egocentric vs landmark-corrected).

Diagnostic seeds only; exploratory, not confirmatory. Two experiments:
  static     - food A only, 12,000 steps
  relocation - A closes and B opens at 6,000, 18,000 steps
  terrain    - homing error x landmark count sweep, static food, 12,000 steps
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
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

from scalar_baseline.config import B0Config, DecayConfig, SimulationConfig  # noqa: E402
from stage5_navigation.diffusion import DiffusingField  # noqa: E402
from stage5_navigation.model import CoarseReturnSimulation  # noqa: E402
from stage5_navigation.path_integration import NavigationConfig, PathIntegrationSimulation  # noqa: E402
from stage5_diagnose_field import shape_metrics  # noqa: E402

SEEDS = tuple(range(2026093001, 2026093011))
OUT = ROOT / "results" / "stage5_diagnostics" / "navigation"
ARENA, NEST, FOOD_A, FOOD_B = 300.0, (150.0, 150.0), (240.0, 150.0), (150.0, 240.0)

# name: (strategy, compass_noise, landmark_count[, sensor_distance])
STATIC = {
    "retrace": ("retrace", None, 0),
    "pi_0.0": ("pi", 0.0, 0), "pi_0.1": ("pi", 0.1, 0), "pi_0.3": ("pi", 0.3, 0),
    "pi_0.6": ("pi", 0.6, 0), "pi_1.0": ("pi", 1.0, 0),
    "pi_0.6_lm30": ("pi", 0.6, 30), "pi_0.6_lm300": ("pi", 0.6, 300),
    "pi_1.0_lm300": ("pi", 1.0, 300),
    # Sensor-geometry check: is a perfectly thin trail simply hard to follow?
    "pi_0.0_sensor2": ("pi", 0.0, 0, 2.0), "pi_0.1_sensor2": ("pi", 0.1, 0, 2.0),
}
RELOCATION = {k: STATIC[k] for k in ("retrace", "pi_0.0", "pi_0.6", "pi_0.6_lm300")}
# Terrain sweep: homing error x landmark density (0 = open ground), static food.
NOISES, LANDMARK_COUNTS = (0.1, 0.3, 0.6, 1.0), (0, 10, 30, 100, 300)
TERRAIN = {f"pi_{n}_lm{c}": ("pi", n, c) for n in NOISES for c in LANDMARK_COUNTS}
# Trail-width check: same strategies on 3-unit cells (wider deposited trail).
WIDTH = {"retrace_cell3": ("retrace", None, 0, 1.0, 3), "pi_0.0_cell3": ("pi", 0.0, 0, 1.0, 3),
         "pi_0.1_cell3": ("pi", 0.1, 0, 1.0, 3), "pi_0.1_lm300_cell3": ("pi", 0.1, 300, 1.0, 3),
         "pi_0.6_cell3": ("pi", 0.6, 0, 1.0, 3), "pi_0.6_lm300_cell3": ("pi", 0.6, 300, 1.0, 3),
         "pi_1.0_cell3": ("pi", 1.0, 0, 1.0, 3), "pi_1.0_lm300_cell3": ("pi", 1.0, 300, 1.0, 3)}
# Pheromone diffusion check (proposal Eq. 1): trails acquire a physical width on 1-unit cells.
BASE_KEYS = ("retrace", "pi_0.0", "pi_0.1", "pi_0.6", "pi_1.0")
DIFFUSION = {}
for d in (0.01, 0.05):
    for key, (strategy, noise, count) in {**{k: STATIC[k][:3] for k in BASE_KEYS},
                                          "pi_0.1_lm300": ("pi", 0.1, 300),
                                          "pi_0.6_lm300": ("pi", 0.6, 300),
                                          "pi_1.0_lm300": ("pi", 1.0, 300)}.items():
        DIFFUSION[f"{key}_D{d}"] = (strategy, noise, count, 1.0, 1, d)
EXPERIMENTS = {"static": (STATIC, 12000, None), "relocation": (RELOCATION, 18000, 6000),
               "terrain": (TERRAIN, 12000, None), "width": (WIDTH, 12000, None),
               "diffusion": (DIFFUSION, 12000, None)}


def landmarks(seed: int, count: int) -> tuple:
    if count == 0:
        return ()
    rng = np.random.default_rng(np.random.SeedSequence([seed, 99]))
    return tuple(map(tuple, rng.uniform(0, ARENA, size=(count, 2)).round(6).tolist()))


def run_one(task: tuple[str, str, int]) -> dict:
    experiment, name, seed = task
    conditions, steps, relocation = EXPERIMENTS[experiment]
    strategy, noise, count, *rest = conditions[name]
    sensor = rest[0] if rest else 1.0
    cell = rest[1] if len(rest) > 1 else 1
    diffusion = rest[2] if len(rest) > 2 else 0.0
    config = SimulationConfig(n_ants=100, steps=steps, seed=seed, arena_size=ARENA, cell_size=cell,
                              nest=NEST, food_a=FOOD_A, food_b=FOOD_B, step_size=0.6, deposit_q=1,
                              contact_radius=0.75, diffusion=0, decay=DecayConfig(half_life_steps=1000),
                              relocation_step=relocation, navigation=B0Config(sensor_distance=sensor))
    if strategy == "retrace":
        sim = CoarseReturnSimulation(config, waypoint_spacing=1)
    else:
        sim = PathIntegrationSimulation(config, NavigationConfig(compass_noise=noise,
                                                                 landmarks=landmarks(seed, count)))
    if diffusion > 0:
        sim.field = DiffusingField(ARENA, cell, config.decay, diffusion=diffusion)
    n = sim.field.concentration.shape[0]
    centres = (np.arange(n) + 0.5) * cell
    fx, fy = np.meshgrid(centres, centres, indexing="ij")
    field_sum, samples = np.zeros_like(sim.field.concentration), 0
    occ = np.zeros((60, 60))
    pickups, trips, follower_steps = {}, [], 0
    near_old_a = []
    start = time.perf_counter()
    while sim.time < steps:
        k = len(sim.ledger.events)
        sim.step()
        for e in sim.ledger.events[k:]:
            if e["event"] == "pickup":
                pickups[e["ant_id"]] = e["time"]
            elif e["event"] == "delivery":
                trips.append(e["time"] - pickups.pop(e["ant_id"]))
        follower_steps += sum(a.role == "follower" for a in sim.ants)
        if sim.time % 10 == 0:
            xy = np.array([a.position for a in sim.ants])
            occ += np.histogram2d(xy[:, 0], xy[:, 1], bins=60, range=[[0, ARENA], [0, ARENA]])[0]
        if sim.time % 100 == 0:
            field_sum += sim.field.concentration
            samples += 1
            near_old_a.append(sum(math.dist(a.position, FOOD_A) <= 10 for a in sim.ants))
    deliveries = [e for e in sim.ledger.events if e["event"] == "delivery"]
    times_a = [e["time"] for e in deliveries if e["source"] == "A"]
    times_b = [e["time"] for e in deliveries if e["source"] == "B"]
    mean_field = field_sum / samples
    run_dir = OUT / experiment / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(run_dir / f"{seed}.npz", mean_field=mean_field, final_field=sim.field.concentration,
                        occupancy=occ, near_old_a=np.array(near_old_a))
    oc = (np.arange(60) + 0.5) * ARENA / 60
    ox, oy = np.meshgrid(oc, oc, indexing="ij")
    row = {"experiment": experiment, "condition": name, "seed": seed, "strategy": strategy,
           "compass_noise": noise, "landmarks": count, "sensor_distance": sensor, "cell_size": cell, "diffusion": diffusion, "steps": steps,
           "deliveries_A": len(times_a), "deliveries_B": len(times_b),
           "delivery_times_A": times_a, "delivery_times_B": times_b,
           "completed_trips": len(trips), "unfinished_trips": len(pickups),
           "return_trip_median": float(np.median(trips)) if trips else None,
           "follower_fraction": follower_steps / (steps * config.n_ants),
           "field_shape": shape_metrics(mean_field, fx, fy, NEST),
           "occupancy_shape": shape_metrics(occ, ox, oy, NEST),
           "wall_seconds": time.perf_counter() - start}
    if strategy == "pi":
        errs = sim.arrival_errors
        row.update({"search_starts": sim.search_starts, "landmark_resets": sim.landmark_resets,
                    "arrival_error_median": float(np.median(errs)) if errs else None,
                    "arrival_error_mean": float(np.mean(errs)) if errs else None})
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=tuple(EXPERIMENTS))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    conditions = EXPERIMENTS[args.experiment][0]
    tasks = [(args.experiment, c, s) for c in conditions for s in SEEDS]
    (OUT / args.experiment).mkdir(parents=True, exist_ok=True)
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for r in pool.map(run_one, tasks):
            rows.append(r)
            print(json.dumps({k: r[k] for k in ("condition", "seed", "deliveries_A", "deliveries_B")}
                             | {"wall": round(r["wall_seconds"], 1)}), flush=True)
    (OUT / args.experiment / "runs_summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
