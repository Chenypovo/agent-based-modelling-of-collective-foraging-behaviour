#!/usr/bin/env python3
"""H1a runs (docs/H1A_ANALYSIS_PLAN.md): calibration, ablation, h1a, robust.

calib    - Step 2: D x threshold pair x {error 0, error 0.1, baseline}, static, 12,000 steps
ablation - Step 3: retrace + error x landmark grid at the chosen trail physics, 12,000 steps
h1a      - Step 4: half-life sweep, relocation at 12,000, 36,000 steps
robust   - Step 5: as h1a at the neighbouring D
Steps 3-5 read the trail physics from results/h1a_baseline/calib/selection.json.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from scalar_baseline.config import B0Config, DecayConfig, SimulationConfig  # noqa: E402
from scalar_baseline.stage4_objective import amended_endpoint  # noqa: E402
from stage5_navigation.diffusion import DiffusingField  # noqa: E402
from stage5_navigation.model import CoarseReturnSimulation  # noqa: E402
from stage5_navigation.path_integration import NavigationConfig, PathIntegrationSimulation  # noqa: E402

OUT = ROOT / "results" / "h1a_baseline"
ARENA, NEST, FOOD_A, FOOD_B = 300.0, (150.0, 150.0), (240.0, 150.0), (150.0, 240.0)
BASE_NOISE, BASE_LANDMARKS, REF_HALF_LIFE = 0.5, 100, 1000
RELOCATION, TOTAL, POST, WINDOW = 12000, 36000, 24000, 1200

SEEDS = {"calib": range(2026210001, 2026210011), "ablation": range(2026230001, 2026230021),
         "h1a": range(2026240001, 2026240021), "robust": range(2026250001, 2026250021)}
D_GRID = (0.0, 0.01, 0.02, 0.05)
THRESHOLDS = ((0.5, 0.25), (0.25, 0.125))
NOISES, LANDMARK_COUNTS = (0.1, 0.3, 0.5, 0.6, 1.0), (0, 10, 30, 100, 300)
HALF_LIVES = (250, 500, 1000, 2000, 4000)


def landmarks(seed: int, count: int) -> tuple:
    if count == 0:
        return ()
    rng = np.random.default_rng(np.random.SeedSequence([seed, 99]))
    return tuple(map(tuple, rng.uniform(0, ARENA, size=(count, 2)).round(6).tolist()))


def selection() -> dict:
    return json.loads((OUT / "calib" / "selection.json").read_text())


def conditions(step: str) -> list[dict]:
    """Each condition: strategy, noise, landmarks, D, thresholds, half_life, steps, relocation."""
    static = {"half_life": REF_HALF_LIFE, "steps": 12000, "relocation": None}
    if step == "calib":
        return [{"name": f"{c}_D{d}_on{on}", "strategy": "pi", "noise": n, "landmarks": lm,
                 "D": d, "on": on, "off": off, **static}
                for d in D_GRID for on, off in THRESHOLDS
                for c, n, lm in (("C1", 0.0, 0), ("C2", 0.1, 0), ("C3", BASE_NOISE, BASE_LANDMARKS))]
    sel = selection()
    physics = {"on": sel["on"], "off": sel["off"]}
    if step == "ablation":
        out = [{"name": "retrace", "strategy": "retrace", "noise": None, "landmarks": 0,
                "D": sel["D"], **physics, **static}]
        out += [{"name": f"pi_{n}_lm{lm}", "strategy": "pi", "noise": n, "landmarks": lm,
                 "D": sel["D"], **physics, **static} for n in NOISES for lm in LANDMARK_COUNTS]
        return out
    d = sel["D"] if step == "h1a" else sel["neighbour_D"]
    return [{"name": f"hl{h}", "strategy": "pi", "noise": BASE_NOISE, "landmarks": BASE_LANDMARKS,
             "D": d, **physics, "half_life": h, "steps": TOTAL, "relocation": RELOCATION}
            for h in HALF_LIVES]


def run_one(task: tuple[dict, int]) -> dict:
    cond, seed = task
    config = SimulationConfig(n_ants=100, steps=cond["steps"], seed=seed, arena_size=ARENA, cell_size=1,
                              nest=NEST, food_a=FOOD_A, food_b=FOOD_B, step_size=0.6, deposit_q=1,
                              contact_radius=0.75, diffusion=0,
                              decay=DecayConfig(half_life_steps=cond["half_life"]),
                              relocation_step=cond["relocation"],
                              navigation=B0Config(signal_on=cond["on"], signal_off=cond["off"]))
    if cond["strategy"] == "retrace":
        sim = CoarseReturnSimulation(config, waypoint_spacing=1)
    else:
        sim = PathIntegrationSimulation(config, NavigationConfig(
            compass_noise=cond["noise"], landmarks=landmarks(seed, cond["landmarks"]),
            deposit_during_search=False))
    if cond["D"] > 0:
        sim.field = DiffusingField(ARENA, 1, config.decay, diffusion=cond["D"])
    pickups, trips, follower_steps = {}, [], 0
    start = time.perf_counter()
    while sim.time < config.steps:
        k = len(sim.ledger.events)
        sim.step()
        for e in sim.ledger.events[k:]:
            if e["event"] == "pickup":
                pickups[e["ant_id"]] = e["time"]
            elif e["event"] == "delivery":
                trips.append(e["time"] - pickups.pop(e["ant_id"]))
        follower_steps += sum(a.role == "follower" for a in sim.ants)
    deliveries = [{"event": "delivery", "source": e["source"], "time": e["time"]}
                  for e in sim.ledger.events if e["event"] == "delivery"]
    times_a = [e["time"] for e in deliveries if e["source"] == "A"]
    row = {**cond, "seed": seed,
           "deliveries_A": len(times_a),
           "deliveries_A_pre": sum(t < RELOCATION for t in times_a),
           "deliveries_B": sum(e["source"] == "B" for e in deliveries),
           "delivery_times_A": times_a,
           "delivery_times_B": [e["time"] for e in deliveries if e["source"] == "B"],
           "return_trip_median": float(np.median(trips)) if trips else None,
           "follower_fraction": follower_steps / (config.steps * config.n_ants),
           "wall_seconds": time.perf_counter() - start}
    if cond["strategy"] == "pi":
        errs = sim.arrival_errors
        row.update({"search_starts": sim.search_starts, "landmark_resets": sim.landmark_resets,
                    "arrival_error_median": float(np.median(errs)) if errs else None,
                    "arrival_records": [[round(e, 4), round(o, 2)] for e, o in sim.arrival_records]})
    if cond["relocation"] is not None:
        ep = amended_endpoint(deliveries, relocation=RELOCATION, post_horizon=POST, window=WINDOW)
        row.update({"tau": ep.tau_rec, "non_recovery": ep.non_recovery, "R_pre": ep.pre_deliveries})
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=tuple(SEEDS))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    os.nice(10)  # low priority so the machine stays usable; inherited by workers
    tasks = [(c, s) for c in conditions(args.step) for s in SEEDS[args.step]]
    out = OUT / args.step
    parts = out / "runs"
    parts.mkdir(parents=True, exist_ok=True)
    part = lambda c, s: parts / f"{c['name']}_{s}.json"  # noqa: E731
    todo = [t for t in tasks if not part(*t).exists()]
    print(f"{len(tasks) - len(todo)} of {len(tasks)} runs already done; running {len(todo)}", flush=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, t): t for t in todo}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            tmp = part(*futures[future]).with_suffix(".tmp")
            tmp.write_text(json.dumps(r) + "\n")
            tmp.replace(part(*futures[future]))  # atomic: a stop never leaves a half-written file
            print(f"[{i}/{len(todo)}] {r['name']} {r['seed']} A={r['deliveries_A']} "
                  f"B={r['deliveries_B']} foll={r['follower_fraction']:.3f} "
                  f"{r['wall_seconds']:.0f}s", flush=True)
    rows = [json.loads(part(*t).read_text()) for t in tasks]
    (out / "runs.json").write_text(json.dumps(rows) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
